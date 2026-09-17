using System.Diagnostics;
using System.Net;
using System.Net.Http;
using System.Windows;
using System.Text;
using System.Text.Json;
using Microsoft.Web.WebView2.Core;
using System.IO;
using System.Web;
using System.Runtime.InteropServices;

namespace AiosShell;

/// <summary>
/// AI-OS 轻量桌面壳：拉起 loopx serve-status + 内嵌静态服务 + WebView2 窗口。
/// 关闭窗口时清理自己拉起的服务进程。
/// </summary>
public partial class MainWindow : Window
{
    private readonly int _webPort = 8799;          // 内嵌静态服务端口
    private const string RemotePasswordEnv = "AIOS_REMOTE_PASSWORD"; // 非回环(手机)访问密码 env
    private const string SessionCookie = "aios_session";             // 手机登录后发放的会话 cookie
    private const int StatusPort = 8766;          // loopx serve-status 端口
    private const int ChatPort = 8767;            // loopx Chat 服务端口（/api/* 写通道）
    private const int OpencodePort = 4400;        // opencode serve（顶栏 Chat 面板，iframe 直连）
    private const int OpenSciencePort = 4401;     // OpenScience serve（顶栏 Chat 面板可选 agent）
    private static readonly string RuntimeRoot = Paths.RuntimeRoot;
    private static readonly string PythonExe = Paths.Python;
    private readonly List<Process> _children = new();
    private static readonly IntPtr _childJob = ChildProcessJob.Create();
    private HttpListener? _listener;
    private string _distRoot = "";

    public MainWindow()
    {
        InitializeComponent();
        Loaded += OnLoaded;
        Closed += OnClosed;
    }

    private async void OnLoaded(object sender, RoutedEventArgs e)
    {
        try
        {
            StartStatusServer();
            StartChatServer();
            StartWebServer();
            StartOpencodeServer();
            StartOpenScienceServer();
            await InitWebViewAsync();
        }
        catch (Exception ex)
        {
            MessageBox.Show($"启动失败: {ex.Message}\n\n{ex}", "AI-OS 面板", MessageBoxButton.OK, MessageBoxImage.Error);
            Close();
        }
    }

    /// <summary>探测端口是否已有服务在监听（防重复拉起导致端口被占+孤儿进程）</summary>
    private static async Task<bool> PortIsListeningAsync(int port)
    {
        try
        {
            using var tcp = new System.Net.Sockets.TcpClient();
            var task = tcp.ConnectAsync("127.0.0.1", port);
            var done = await Task.WhenAny(task, Task.Delay(1500));
            if (done != task || !tcp.Connected) return false;
            tcp.Close();
            return true;
        }
        catch { return false; }
    }

    /// <summary>拉起 loopx serve-status（本地回环；命令缺失时静默降级，不阻塞 UI）</summary>
    private async void StartStatusServer()
    {
        try
        {
            if (await PortIsListeningAsync(StatusPort)) return;
            var p = StartHidden(Paths.LoopxCmd, new[]
            {
                "--runtime-root", RuntimeRoot,
                "serve-status",
                "--port", StatusPort.ToString(),
                "--global-registry",
            });
            if (p == null) return;
            DrainProcessPipes(p);
            TrackChild(p);
        }
        catch { /* 可选外部组件：缺失时降级 */ }
    }

    /// <summary>拉起 loopx Chat 服务（serve_chat，8767，供 /api/* 写通道；python/依赖缺失时静默降级）</summary>
    private async void StartChatServer()
    {
        try
        {
            if (await PortIsListeningAsync(ChatPort)) return;
            var psi = new ProcessStartInfo(PythonExe)
            {
                ArgumentList = { Paths.ChatScript },
                WindowStyle = ProcessWindowStyle.Hidden,
                UseShellExecute = false,
                CreateNoWindow = true,
                WorkingDirectory = Paths.Root,
                RedirectStandardOutput = true,
                RedirectStandardError = true,
                StandardOutputEncoding = System.Text.Encoding.UTF8,
                StandardErrorEncoding = System.Text.Encoding.UTF8,
            };
            // Python 默认按 locale(GBK) 读 ACP agent 子进程输出，遇 UTF-8 中文抛 UnicodeDecodeError → apply 424
            psi.Environment["PYTHONUTF8"] = "1";
            var p = Process.Start(psi);
            if (p == null) return;
            DrainProcessPipes(p);
            TrackChild(p);
        }
        catch { /* 可选外部组件：缺失时降级 */ }
    }

    /// <summary>重定向了 stdout/stderr 但无人读取 → 管道缓冲填满后子进程写日志永久阻塞（serve_chat 卡死根因）。异步排空防止此问题。</summary>
    private static void DrainProcessPipes(Process p)
    {
        p.OutputDataReceived += (_, _) => { };
        p.ErrorDataReceived += (_, _) => { };
        p.BeginOutputReadLine();
        p.BeginErrorReadLine();
    }

    /// <summary>登记子进程：加入连坐任务组，壳被强杀时由内核一并终结（防孤儿）</summary>
    private void TrackChild(Process p)
    {
        _children.Add(p);
        ChildProcessJob.Assign(_childJob, p);
    }

    /// <summary>隐藏启动外部命令（经 cmd.exe 解析 .cmd/.exe 垫片；命令缺失或启动失败返回 null，调用方静默降级）。</summary>
    private static Process? StartHidden(string command, IEnumerable<string> args)
    {
        var psi = new ProcessStartInfo("cmd.exe")
        {
            UseShellExecute = false,
            CreateNoWindow = true,
            WindowStyle = ProcessWindowStyle.Hidden,
            WorkingDirectory = Paths.Root,
            RedirectStandardOutput = true,
            RedirectStandardError = true,
            StandardOutputEncoding = System.Text.Encoding.UTF8,
            StandardErrorEncoding = System.Text.Encoding.UTF8,
        };
        psi.ArgumentList.Add("/c");
        psi.ArgumentList.Add(command);
        foreach (var a in args) psi.ArgumentList.Add(a);
        try { return Process.Start(psi); } catch { return null; }
    }

    /// <summary>拉起 opencode serve（顶栏 Chat 面板 iframe 目标，经 /oc/ 代理注入认证；缺失时静默降级）</summary>
    private async void StartOpencodeServer()
    {
        try
        {
            if (await PortIsListeningAsync(OpencodePort)) return;
            // 经 cmd 解析 npm 垫片（opencode.cmd）；凭据走用户级环境变量（HKCU:\Environment）自动继承
            var p = StartHidden(Paths.OpencodeExe, new[] { "serve", "--port", OpencodePort.ToString(), "--hostname", "127.0.0.1" });
            if (p == null) return;
            DrainProcessPipes(p);
            TrackChild(p);
        }
        catch { /* 可选外部组件：缺失时降级 */ }
    }

    /// <summary>拉起 OpenScience serve（顶栏 Chat 面板可选 agent；缺失时静默降级）</summary>
    private async void StartOpenScienceServer()
    {
        try
        {
            if (await PortIsListeningAsync(OpenSciencePort)) return;
            var p = StartHidden(Paths.OpenScienceJs, new[] { "serve", "--port", OpenSciencePort.ToString() });
            if (p == null) return;
            DrainProcessPipes(p);
            TrackChild(p);
        }
        catch { /* 可选外部组件：缺失时降级 */ }
    }

    /// <summary>内嵌静态服务：serve dashboard dist + /status.json 转发到 8766</summary>
    private void StartWebServer()
    {
        // 解析 dist 根：优先打包随附的 dashboard/dist，回退到 l4-os/dashboard/dist
        var local = Path.Combine(AppContext.BaseDirectory, "dashboard-dist");
        _distRoot = Directory.Exists(Path.Combine(local, "index.html"))
            ? local
            : Paths.DashboardDist;

        _listener = new HttpListener();
        _listener.Prefixes.Add($"http://127.0.0.1:{_webPort}/");
        _listener.Start();
        _ = Task.Run(HandleRequestsAsync);
    }

    private async Task HandleRequestsAsync()
    {
        while (_listener?.IsListening == true)
        {
            HttpListenerContext ctx;
            try { ctx = await _listener.GetContextAsync(); }
            catch { break; }

            _ = Task.Run(() => ServeAsync(ctx));
        }
    }

    /// <summary>回环请求（桌面 WebView2 / 本机）直接放行</summary>
    private static bool IsLoopback(IPEndPoint? ep) => ep?.Address is IPAddress a && IPAddress.IsLoopback(a);

    /// <summary>手机会话是否已通过密码（校验 session cookie 是否等于当前密码）</summary>
    private static bool IsAuthorized(HttpListenerContext ctx)
    {
        var cookie = ctx.Request.Cookies[SessionCookie];
        if (cookie == null) return false;
        return string.Equals(cookie.Value, RemotePassword(), StringComparison.Ordinal);
    }

    /// <summary>远程访问密码：优先 AIOS_REMOTE_PASSWORD，回退 OPENCODE_SERVER_PASSWORD</summary>
    private static string? RemotePassword() =>
        Environment.GetEnvironmentVariable(RemotePasswordEnv, EnvironmentVariableTarget.User)
        ?? Environment.GetEnvironmentVariable("OPENCODE_SERVER_PASSWORD")
        ?? Environment.GetEnvironmentVariable(RemotePasswordEnv);

    /// <summary>POST /login：校验密码，成功则种 session cookie 并回首页</summary>
    private async Task HandleLoginAsync(HttpListenerContext ctx)
    {
        using var reader = new StreamReader(ctx.Request.InputStream, Encoding.UTF8);
        var body = await reader.ReadToEndAsync();
        var pw = HttpUtility.ParseQueryString(body)["password"];
        var valid = !string.IsNullOrEmpty(pw) && pw == RemotePassword();
        if (!valid)
        {
            await ServeLoginPageAsync(ctx, error: true);
            return;
        }
        ctx.Response.StatusCode = 302;
        ctx.Response.Headers["Location"] = "/";
        ctx.Response.Headers["Set-Cookie"] = $"{SessionCookie}={RemotePassword()}; Path=/; HttpOnly";
        ctx.Response.Close();
    }

    /// <summary>返回极简登录页（静态字符串，无外部依赖）</summary>
    private async Task ServeLoginPageAsync(HttpListenerContext ctx, bool error = false)
    {
        var html = "<!doctype html><html><head><meta charset=utf-8><meta name=viewport content=\"width=device-width,initial-scale=1\">"
            + "<title>AI-OS 远程访问</title></head><body style=\"font-family:system-ui;display:flex;align-items:center;justify-content:center;min-height:100vh;background:#0b0e17;color:#e5e7eb\">"
            + "<form method=post action=/login style=\"display:flex;flex-direction:column;gap:12px;width:280px\">"
            + "<h2 style=margin:0>AI-OS</h2>"
            + (error ? "<p style=\"color:#f87171;margin:0\">密码错误</p>" : "")
            + "<input type=password name=password placeholder=\"访问密码\" required "
            + "style=\"padding:10px;border-radius:8px;border:1px solid #374151;background:#111827;color:#e5e7eb\">"
            + "<button type=submit style=\"padding:10px;border-radius:8px;border:0;background:#3b82f6;color:#fff;cursor:pointer\">进入</button>"
            + "</form></body></html>";
        var bytes = Encoding.UTF8.GetBytes(html);
        ctx.Response.StatusCode = error ? 401 : 200;
        ctx.Response.ContentType = "text/html; charset=utf-8";
        ctx.Response.ContentLength64 = bytes.Length;
        await ctx.Response.OutputStream.WriteAsync(bytes);
        ctx.Response.Close();
    }

    private async Task ServeAsync(HttpListenerContext ctx)
    {
        try
        {
            var path = ctx.Request.Url?.AbsolutePath ?? "/";
            // 认证 gate：桌面回环直放行；非回环(手机)须过密码/session
            if (!IsLoopback(ctx.Request.RemoteEndPoint))
            {
                if (path == "/login" && ctx.Request.HttpMethod == "POST")
                {
                    await HandleLoginAsync(ctx);
                    return;
                }
                if (!IsAuthorized(ctx))
                {
                    await ServeLoginPageAsync(ctx);
                    return;
                }
            }
            if (path.StartsWith("/status.json", StringComparison.OrdinalIgnoreCase)
                || path.StartsWith("/healthz", StringComparison.OrdinalIgnoreCase))
            {
                await ProxyToStatusAsync(ctx, path);
                return;
            }
            if (path.StartsWith("/graph-data", StringComparison.OrdinalIgnoreCase))
            {
                await ServeGraphDataAsync(ctx);
                return;
            }
            if (path.StartsWith("/wfctl", StringComparison.OrdinalIgnoreCase))
            {
                await ServeWfctlAsync(ctx);
                return;
            }
            if (path.StartsWith("/api/", StringComparison.OrdinalIgnoreCase))
            {
                await ProxyToChatAsync(ctx, path);
                return;
            }
            // 远程控制写端点（手机 5 项功能中的 3 项）
            if (path.StartsWith("/goal/", StringComparison.OrdinalIgnoreCase))
            {
                await ServeLoopxControlAsync(ctx, "goal", path);
                return;
            }
            if (path.StartsWith("/gate/", StringComparison.OrdinalIgnoreCase))
            {
                await ServeLoopxControlAsync(ctx, "gate", path);
                return;
            }
            if (path.StartsWith("/config/", StringComparison.OrdinalIgnoreCase))
            {
                await ServeLoopxControlAsync(ctx, "config", path);
                return;
            }
            await ServeStaticAsync(ctx, path);
        }
        catch { try { ctx.Response.StatusCode = 500; ctx.Response.Close(); } catch { } }
    }

    /// <summary>把 /status.json /healthz 转发到 loopx Chat 服务（其 /status.json 投影包含全部 goal；serve-status 仅含运行过 run 的 goal）</summary>
    private static async Task ProxyToStatusAsync(HttpListenerContext ctx, string path)
    {
        using var client = new HttpClient { Timeout = TimeSpan.FromSeconds(8) };
        HttpResponseMessage resp;
        try
        {
            resp = await client.GetAsync($"http://127.0.0.1:{ChatPort}{path}");
        }
        catch (Exception)
        {
            ctx.Response.StatusCode = 502;
            ctx.Response.ContentType = "application/json";
            ctx.Response.Headers["Access-Control-Allow-Origin"] = "*";
            var err = System.Text.Encoding.UTF8.GetBytes("{\"ok\":false,\"error\":\"chat upstream unavailable\"}");
            await ctx.Response.OutputStream.WriteAsync(err);
            ctx.Response.Close();
            return;
        }
        var body = await resp.Content.ReadAsByteArrayAsync();
        ctx.Response.StatusCode = (int)resp.StatusCode;
        ctx.Response.ContentType = resp.Content.Headers.ContentType?.ToString() ?? "application/json";
        ctx.Response.Headers["Access-Control-Allow-Origin"] = "*";
        await ctx.Response.OutputStream.WriteAsync(body);
        ctx.Response.Close();
    }

    /// <summary>把 /api/* 转发到 loopx Chat 服务（保留 method / query / body；8s 超时快速失败防级联卡死）</summary>
    private static async Task ProxyToChatAsync(HttpListenerContext ctx, string path)
    {
        using var client = new HttpClient { Timeout = TimeSpan.FromSeconds(8) };
        var target = $"http://127.0.0.1:{ChatPort}{ctx.Request.Url?.PathAndQuery}";
        using var upstream = new HttpRequestMessage(new System.Net.Http.HttpMethod(ctx.Request.HttpMethod), target);
        if (ctx.Request.HttpMethod is "POST" or "PUT" or "PATCH")
        {
            using var ms = new MemoryStream();
            await ctx.Request.InputStream.CopyToAsync(ms);
            upstream.Content = new ByteArrayContent(ms.ToArray());
            if (ctx.Request.ContentType != null)
            {
                upstream.Content.Headers.ContentType =
                    new System.Net.Http.Headers.MediaTypeHeaderValue(ctx.Request.ContentType.Split(';')[0].Trim());
            }
        }
        HttpResponseMessage resp;
        try
        {
            resp = await client.SendAsync(upstream);
        }
        catch (Exception)
        {
            ctx.Response.StatusCode = 502;
            ctx.Response.ContentType = "application/json";
            ctx.Response.Headers["Access-Control-Allow-Origin"] = "*";
            var err = System.Text.Encoding.UTF8.GetBytes("{\"ok\":false,\"error\":\"chat upstream unavailable\"}");
            await ctx.Response.OutputStream.WriteAsync(err);
            ctx.Response.Close();
            return;
        }
        var body = await resp.Content.ReadAsByteArrayAsync();
        ctx.Response.StatusCode = (int)resp.StatusCode;
        var ct = resp.Content.Headers.ContentType?.ToString();
        if (ct != null) ctx.Response.ContentType = ct;
        ctx.Response.Headers["Access-Control-Allow-Origin"] = "*";
        await ctx.Response.OutputStream.WriteAsync(body);
        ctx.Response.Close();
    }

    /// <summary>serve dashboard dist 静态文件（SPA 回退到 index.html）</summary>
    private async Task ServeStaticAsync(HttpListenerContext ctx, string path)
    {
        var rel = path.TrimStart('/');
        if (string.IsNullOrEmpty(rel)) rel = "index.html";
        var file = Path.GetFullPath(Path.Combine(_distRoot, rel));

        if (!file.StartsWith(_distRoot, StringComparison.OrdinalIgnoreCase) || !File.Exists(file))
            file = Path.Combine(_distRoot, "index.html");

        var bytes = await File.ReadAllBytesAsync(file);
        ctx.Response.ContentType = MimeType(Path.GetExtension(file));
        ctx.Response.Headers["Cache-Control"] = "no-cache";
        await ctx.Response.OutputStream.WriteAsync(bytes);
        ctx.Response.Close();
    }

    /// <summary>星空背景数据：调 build_graph_data.py 扫 vault 输出 graph JSON</summary>
    private static async Task ServeGraphDataAsync(HttpListenerContext ctx)
    {
        var psi = new ProcessStartInfo(Paths.Python)
        {
            ArgumentList = { Paths.BuildGraphDataPy, Paths.Vault },
            UseShellExecute = false,
            CreateNoWindow = true,
            RedirectStandardOutput = true,
            RedirectStandardError = true,
            StandardOutputEncoding = System.Text.Encoding.UTF8,
        };
        using var p = Process.Start(psi) ?? throw new InvalidOperationException("无法启动 build_graph_data.py");
        var stdout = await p.StandardOutput.ReadToEndAsync();
        var stderr = await p.StandardError.ReadToEndAsync();
        await p.WaitForExitAsync();

        if (p.ExitCode != 0)
        {
            ctx.Response.StatusCode = 500;
            var err = System.Text.Encoding.UTF8.GetBytes($"{{ \"ok\": false, \"error\": \"{stderr.Replace("\"", "'")}\" }}");
            ctx.Response.ContentType = "application/json";
            await ctx.Response.OutputStream.WriteAsync(err);
            ctx.Response.Close();
            return;
        }

        var bytes = System.Text.Encoding.UTF8.GetBytes(stdout);
        ctx.Response.StatusCode = 200;
        ctx.Response.ContentType = "application/json";
        ctx.Response.Headers["Access-Control-Allow-Origin"] = "*";
        ctx.Response.Headers["Cache-Control"] = "no-cache";
        await ctx.Response.OutputStream.WriteAsync(bytes);
        ctx.Response.Close();
    }

    /// <summary>wfctl 代理：调 wfctl.py 暴露 list/catalog/render/status/trigger/run-agent/agents/agents-register/agents-unregister 接口给前端</summary>
    private static async Task ServeWfctlAsync(HttpListenerContext ctx)
    {
        var path = ctx.Request.Url?.AbsolutePath ?? "";
        string? sub = null;
        if (path.StartsWith("/wfctl/", StringComparison.OrdinalIgnoreCase))
            sub = path.Substring("/wfctl/".Length);

        // 壳侧直连端点（不走 wfctl.py）：服务探测 / 体检 / 配置读写
        if (sub is "services") { await ServeServicesAsync(ctx); return; }
        if (sub is "diagnostics") { await ServeDiagnosticsAsync(ctx); return; }
        if (sub is "config-get" or "config-set") { await ServeConfigAsync(ctx, sub!); return; }

        var args = new List<string> { Paths.WfctlPy };
        var name = ctx.Request.QueryString["name"];

        if (sub is "trigger" || sub is "render" || sub is "status")
        {
            args.Add(sub!);
            if (!string.IsNullOrEmpty(name)) args.Add(name);
            // trigger 额外接收其它 query 参数作为 k=v 工作流变量
            if (sub == "trigger")
                foreach (string? k in ctx.Request.QueryString.AllKeys)
                    if (k is not null && k != "name")
                        args.Add($"{k}={ctx.Request.QueryString[k]}");
        }
        else if (sub is "catalog")
        {
            args.Add("catalog");
        }
        else if (sub is "run-agent")
        {
            // spec 直跑：spec 名 + 其它 query 参数作为 --input k=v
            args.Add("run-agent");
            var spec = ctx.Request.QueryString["spec"];
            if (!string.IsNullOrEmpty(spec)) args.Add(spec);
            foreach (string? k in ctx.Request.QueryString.AllKeys)
                if (k is not null && k != "spec")
                    args.Add($"{k}={ctx.Request.QueryString[k]}");
        }
        else if (sub is "agents")
        {
            args.Add("agents");
        }
        else if (sub is "agents-register")
        {
            args.Add("agents-register");
            var agentId = ctx.Request.QueryString["agent_id"];
            if (!string.IsNullOrEmpty(agentId)) { args.Add("--agent-id"); args.Add(agentId); }
            var goalId = ctx.Request.QueryString["goal_id"];
            if (!string.IsNullOrEmpty(goalId)) { args.Add("--goal-id"); args.Add(goalId); }
            var exec = ctx.Request.QueryString["execute"];
            if (exec == "1" || string.Equals(exec, "true", StringComparison.OrdinalIgnoreCase))
                args.Add("--execute");
        }
        else if (sub is "agents-unregister")
        {
            args.Add("agents-unregister");
            var agentId = ctx.Request.QueryString["agent_id"];
            if (!string.IsNullOrEmpty(agentId)) { args.Add("--agent-id"); args.Add(agentId); }
            var goalId = ctx.Request.QueryString["goal_id"];
            if (!string.IsNullOrEmpty(goalId)) { args.Add("--goal-id"); args.Add(goalId); }
            var exec = ctx.Request.QueryString["execute"];
            if (exec == "1" || string.Equals(exec, "true", StringComparison.OrdinalIgnoreCase))
                args.Add("--execute");
        }
        else if (sub is "agents-declare")
        {
            args.Add("agents-declare");
            foreach (var key in new[] { "name", "description", "model", "tools", "body" })
            {
                var val = ctx.Request.QueryString[key];
                if (!string.IsNullOrEmpty(val)) { args.Add("--" + key); args.Add(val); }
            }
        }
        else if (sub is "agents-suggest")
        {
            // AI 填充：brief → 身份草案建议（只读，不入盘）
            args.Add("agents-suggest");
            var brief = ctx.Request.QueryString["brief"];
            if (!string.IsNullOrEmpty(brief)) { args.Add("--brief"); args.Add(brief); }
        }
        else
        {
            args.Add("list");
        }

        var psi = new ProcessStartInfo(PythonExe)
        {
            ArgumentList = { },
            UseShellExecute = false,
            CreateNoWindow = true,
            RedirectStandardOutput = true,
            RedirectStandardError = true,
            StandardOutputEncoding = System.Text.Encoding.UTF8,
            StandardErrorEncoding = System.Text.Encoding.UTF8,
        };
        foreach (var a in args) psi.ArgumentList.Add(a);

        using var p = Process.Start(psi) ?? throw new InvalidOperationException("无法启动 wfctl.py");
        var stdout = await p.StandardOutput.ReadToEndAsync();
        var stderr = await p.StandardError.ReadToEndAsync();
        await p.WaitForExitAsync();

        ctx.Response.StatusCode = p.ExitCode == 0 ? 200 : 500;
        ctx.Response.ContentType = "application/json; charset=utf-8";
        ctx.Response.Headers["Access-Control-Allow-Origin"] = "*";
        ctx.Response.Headers["Cache-Control"] = "no-cache";

        if (p.ExitCode == 0 && sub != "trigger" && sub != "run-agent")
        {
            // list/catalog/render/status/agents* 输出已是 JSON；status 是纯文本，整包成 JSON
            if (sub == "status")
            {
                var txt = System.Text.Encoding.UTF8.GetBytes(
                    "{\"text\":" + System.Text.Json.JsonSerializer.Serialize(stdout.Trim()) + "}");
                await ctx.Response.OutputStream.WriteAsync(txt);
            }
            else
            {
                var bytes = System.Text.Encoding.UTF8.GetBytes(stdout);
                await ctx.Response.OutputStream.WriteAsync(bytes);
            }
        }
        else
        {
            // trigger（或出错）：包成 JSON {exit, output}
            var obj = System.Text.Json.JsonSerializer.Serialize(new
            {
                exit = p.ExitCode,
                output = stdout,
                error = stderr,
            });
            var b = System.Text.Encoding.UTF8.GetBytes(obj);
            await ctx.Response.OutputStream.WriteAsync(b);
        }
        ctx.Response.Close();
    }

    /// <summary>服务连通状态：壳 TCP 探测自身相关服务端口（设置页/体检用）</summary>
    private static async Task ServeServicesAsync(HttpListenerContext ctx)
    {
        var probes = new (string Id, string Name, int Port, string Url)[]
        {
            ("console", "控制台静态服务（壳）", 8799, "http://127.0.0.1:8799/"),
            ("status", "loopx 状态服务", 8766, "http://127.0.0.1:8766/status.json"),
            ("chat", "Chat 写通道", 8767, "http://127.0.0.1:8767/"),
            ("opencode-modelz", "opencode 模型通道（kind=opencode）", 4399, "http://127.0.0.1:4399/"),
            ("opencode", "opencode 面板", 4400, "http://127.0.0.1:4400/"),
            ("openscience", "OpenScience 面板", 4401, "http://127.0.0.1:4401/"),
        };
        var items = new List<object>();
        foreach (var pr in probes)
        {
            var up = await PortIsListeningAsync(pr.Port);
            items.Add(new { id = pr.Id, name = pr.Name, port = pr.Port, url = pr.Url, up });
        }
        ctx.Response.StatusCode = 200;
        ctx.Response.ContentType = "application/json; charset=utf-8";
        ctx.Response.Headers["Access-Control-Allow-Origin"] = "*";
        ctx.Response.Headers["Cache-Control"] = "no-cache";
        await WriteAsync(ctx, JsonSerializer.Serialize(new { ok = true, services = items }));
        ctx.Response.Close();
    }

    /// <summary>体检：转发 l2-memory/scripts/diagnostics.py（quick/ping），stdout JSON 原样返回</summary>
    private static async Task ServeDiagnosticsAsync(HttpListenerContext ctx)
    {
        var mode = ctx.Request.QueryString["mode"] == "ping" ? "ping" : "quick";
        var psi = new ProcessStartInfo(PythonExe)
        {
            UseShellExecute = false,
            CreateNoWindow = true,
            RedirectStandardOutput = true,
            RedirectStandardError = true,
            StandardOutputEncoding = Encoding.UTF8,
            StandardErrorEncoding = Encoding.UTF8,
        };
        psi.ArgumentList.Add(Path.Combine(Paths.Root, "l2-memory", "scripts", "diagnostics.py"));
        psi.ArgumentList.Add("--mode");
        psi.ArgumentList.Add(mode);

        using var p = Process.Start(psi) ?? throw new InvalidOperationException("无法启动 diagnostics.py");
        var stdout = await p.StandardOutput.ReadToEndAsync();
        var stderr = await p.StandardError.ReadToEndAsync();
        await p.WaitForExitAsync();

        ctx.Response.ContentType = "application/json; charset=utf-8";
        ctx.Response.Headers["Access-Control-Allow-Origin"] = "*";
        ctx.Response.Headers["Cache-Control"] = "no-cache";
        if (stdout.TrimStart().StartsWith("{"))
        {
            ctx.Response.StatusCode = 200;
            await WriteAsync(ctx, stdout);
        }
        else
        {
            ctx.Response.StatusCode = 500;
            await WriteAsync(ctx, JsonSerializer.Serialize(new { exit = p.ExitCode, output = stdout, error = stderr }));
        }
        ctx.Response.Close();
    }

    /// <summary>配置读写：config-get 返回原文；config-set 校验 + 备份 + 原子写（UTF-8 无 BOM）。json 从 query 或 POST body 取。</summary>
    private static async Task ServeConfigAsync(HttpListenerContext ctx, string sub)
    {
        var cfgPath = Path.Combine(Paths.Root, "l2-memory", "config.json");
        ctx.Response.ContentType = "application/json; charset=utf-8";
        ctx.Response.Headers["Access-Control-Allow-Origin"] = "*";
        ctx.Response.Headers["Cache-Control"] = "no-cache";

        try
        {
            if (sub == "config-get")
            {
                if (!File.Exists(cfgPath))
                    throw new InvalidOperationException("config.json 不存在（可从 config.example.json 复制）");
                var text = await File.ReadAllTextAsync(cfgPath, Encoding.UTF8);
                ctx.Response.StatusCode = 200;
                await WriteAsync(ctx, JsonSerializer.Serialize(new { ok = true, path = cfgPath, text }));
                ctx.Response.Close();
                return;
            }

            // config-set
            string? json = ctx.Request.QueryString["json"];
            if (string.IsNullOrEmpty(json) && ctx.Request.HasEntityBody)
            {
                using var reader = new StreamReader(ctx.Request.InputStream, Encoding.UTF8);
                json = await reader.ReadToEndAsync();
            }
            if (string.IsNullOrEmpty(json)) throw new InvalidOperationException("缺 json（query 或 body）");

            using (var doc = JsonDocument.Parse(json))
            {
                if (!doc.RootElement.TryGetProperty("models", out var models) ||
                    !models.TryGetProperty("default", out var def) ||
                    string.IsNullOrWhiteSpace(def.GetString()))
                    throw new InvalidOperationException("校验失败：缺少 models.default");
            }

            var backup = cfgPath + ".bak-" + DateTime.Now.ToString("yyyyMMdd-HHmmss");
            if (File.Exists(cfgPath)) File.Copy(cfgPath, backup, overwrite: true);
            await File.WriteAllTextAsync(cfgPath, json, new UTF8Encoding(false));
            ctx.Response.StatusCode = 200;
            await WriteAsync(ctx, JsonSerializer.Serialize(new
            {
                ok = true,
                path = cfgPath,
                backup = Path.GetFileName(backup),
                bytes = Encoding.UTF8.GetByteCount(json),
            }));
        }
        catch (Exception ex)
        {
            ctx.Response.StatusCode = 500;
            await WriteAsync(ctx, JsonSerializer.Serialize(new { ok = false, error = ex.Message }));
        }
        ctx.Response.Close();
    }

    private static async Task WriteAsync(HttpListenerContext ctx, string s)
    {
        var b = Encoding.UTF8.GetBytes(s);
        await ctx.Response.OutputStream.WriteAsync(b);
    }

    /// <summary>
    /// 远程控制写端点（/goal/ /gate/ /config/）：把子路径 + query 参数转发为 loopx CLI 调用。
    /// 例：/goal/start?text=...    → loopx start-goal --guided --project ... --host-surface other-agent --goal-text ...
    ///     /goal/stop?id=...      → loopx goal-lifecycle --goal-id ... --operation stop --execute
    ///     /gate/approve?goal=..&reason=.. → loopx operator-gate --goal-id ... --decision approve --reason-summary ...
    ///     /config/apply?goal=..&k=v      → loopx configure-goal --goal-id ... --k v
    /// </summary>
    private static async Task ServeLoopxControlAsync(HttpListenerContext ctx, string kind, string path)
    {
        // 解析 /goal/start 之类：kind + sub 拼成 loopx 命令
        var sub = path.Substring($"/{kind}/".Length).Trim('/');
        var args = new List<string>();
        if (kind == "goal" && sub == "start")
        {
            var text = ctx.Request.QueryString["text"];
            if (string.IsNullOrEmpty(text)) { await JsonErrorAsync(ctx, "缺 text 参数"); return; }
            args.Add("start-goal");
            args.Add("--guided");
            args.Add("--project"); args.Add(Paths.Root);
            args.Add("--host-surface"); args.Add("other-agent");
            args.Add("--goal-text"); args.Add(text!);
        }
        else if (kind == "goal" && sub == "stop")
        {
            var gid = ctx.Request.QueryString["id"];
            if (string.IsNullOrEmpty(gid)) { await JsonErrorAsync(ctx, "缺 id 参数"); return; }
            args.Add("goal-lifecycle");
            args.Add("--goal-id"); args.Add(gid!);
            args.Add("--operation"); args.Add("stop");
            args.Add("--execute");
        }
        else if (kind == "gate" && sub is "approve" or "reject")
        {
            var gid = ctx.Request.QueryString["goal"];
            var reason = ctx.Request.QueryString["reason"];
            if (string.IsNullOrEmpty(gid) || string.IsNullOrEmpty(reason))
            { await JsonErrorAsync(ctx, "缺 goal/reason 参数"); return; }
            args.Add("operator-gate");
            args.Add("--goal-id"); args.Add(gid!);
            args.Add("--decision"); args.Add(sub == "approve" ? "approve" : "reject");
            args.Add("--reason-summary"); args.Add(reason!);
            args.Add("--format"); args.Add("json");
        }
        else if (kind == "config" && sub == "apply")
        {
            var gid = ctx.Request.QueryString["goal"];
            if (string.IsNullOrEmpty(gid)) { await JsonErrorAsync(ctx, "缺 goal 参数"); return; }
            args.Add("configure-goal");
            args.Add("--goal-id"); args.Add(gid!);
            // 其余 query 参数直接作为 --key value 传给 configure-goal
            foreach (string? k in ctx.Request.QueryString.AllKeys)
            {
                if (k is not null && k != "goal")
                {
                    args.Add($"--{k}");
                    args.Add(ctx.Request.QueryString[k] ?? "");
                }
            }
        }
        else
        {
            await JsonErrorAsync(ctx, $"未知控制端点 /{kind}/{sub}");
            return;
        }

        var psi = new ProcessStartInfo(Paths.LoopxCmd)
        {
            WorkingDirectory = Paths.Root,
            UseShellExecute = false,
            CreateNoWindow = true,
            RedirectStandardOutput = true,
            RedirectStandardError = true,
            StandardOutputEncoding = System.Text.Encoding.UTF8,
            StandardErrorEncoding = System.Text.Encoding.UTF8,
        };
        foreach (var a in args) psi.ArgumentList.Add(a);

        using var p = Process.Start(psi);
        if (p == null) { await JsonErrorAsync(ctx, "无法启动 loopx"); return; }
        var stdout = await p.StandardOutput.ReadToEndAsync();
        var stderr = await p.StandardError.ReadToEndAsync();
        await p.WaitForExitAsync();

        var obj = System.Text.Json.JsonSerializer.Serialize(new
        {
            exit = p.ExitCode,
            output = stdout,
            error = stderr,
        });
        var b = System.Text.Encoding.UTF8.GetBytes(obj);
        ctx.Response.StatusCode = p.ExitCode == 0 ? 200 : 500;
        ctx.Response.ContentType = "application/json; charset=utf-8";
        ctx.Response.Headers["Access-Control-Allow-Origin"] = "*";
        await ctx.Response.OutputStream.WriteAsync(b);
        ctx.Response.Close();
    }

    private static async Task JsonErrorAsync(HttpListenerContext ctx, string msg)
    {
        var b = System.Text.Encoding.UTF8.GetBytes("{\"exit\":-1,\"error\":" + System.Text.Json.JsonSerializer.Serialize(msg) + "}");
        ctx.Response.StatusCode = 400;
        ctx.Response.ContentType = "application/json; charset=utf-8";
        await ctx.Response.OutputStream.WriteAsync(b);
        ctx.Response.Close();
    }

    private static string MimeType(string ext) => ext switch
    {
        ".html" => "text/html; charset=utf-8",
        ".js" => "text/javascript",
        ".css" => "text/css",
        ".json" => "application/json",
        ".svg" => "image/svg+xml",
        ".png" => "image/png",
        ".ico" => "image/x-icon",
        ".woff" or ".woff2" => "font/woff2",
        _ => "application/octet-stream",
    };

    private async Task InitWebViewAsync()
    {
        var env = await CoreWebView2Environment.CreateAsync(
            userDataFolder: Path.Combine(AppContext.BaseDirectory, "webview2-data"));
        await webView.EnsureCoreWebView2Async(env);
        // 注入 opencode serve 的 Basic auth（凭据来自用户级 env，避免 iframe 弹认证框）
        webView.CoreWebView2.BasicAuthenticationRequested += OnBasicAuthRequested;
        webView.CoreWebView2.Navigate($"http://127.0.0.1:{_webPort}/");
        webView.CoreWebView2.Settings.AreDevToolsEnabled = true;
    }

    /// <summary>WebView2 遇到 Basic auth 时自动注入 opencode serve 凭据</summary>
    private static void OnBasicAuthRequested(object? sender, CoreWebView2BasicAuthenticationRequestedEventArgs e)
    {
        var password = Environment.GetEnvironmentVariable("OPENCODE_SERVER_PASSWORD", EnvironmentVariableTarget.User)
                       ?? Environment.GetEnvironmentVariable("OPENCODE_SERVER_PASSWORD");
        if (string.IsNullOrEmpty(password)) return;
        if (e.Uri.StartsWith($"http://127.0.0.1:{OpencodePort}", StringComparison.OrdinalIgnoreCase))
        {
            e.Response.UserName = "opencode";
            e.Response.Password = password;
            e.Cancel = false;
        }
    }

    /// <summary>关闭窗口：停静态服务 + kill 自己拉起的 serve-status</summary>
    private void OnClosed(object? sender, EventArgs e)
    {
        try { _listener?.Stop(); } catch { }
        foreach (var p in _children)
        {
            try { if (!p.HasExited) p.Kill(true); } catch { }
        }
        KillOrphanedServices();
    }

    /// <summary>兜底清理本壳拉起的服务进程（含绑定失败未退出的孤儿）。按命令行特征匹配，避免误杀其它来源进程。</summary>
    private static void KillOrphanedServices()
    {
        try
        {
            var keep = new HashSet<int> { Environment.ProcessId };
            using var searcher = new System.Management.ManagementObjectSearcher(
                "SELECT ProcessId, CommandLine FROM Win32_Process WHERE Name='python.exe' OR Name='loopx.exe' OR Name='node.exe' OR Name='opencode.exe'");
            foreach (var obj in searcher.Get())
            {
                try
                {
                    using var proc = (System.Management.ManagementObject)obj;
                    var cmd = Convert.ToString(proc["CommandLine"]) ?? "";
                    var pid = Convert.ToInt32(proc["ProcessId"]);
                    var isOurs = cmd.Contains("serve_chat.py", StringComparison.OrdinalIgnoreCase)
                        || cmd.Contains("serve-status", StringComparison.OrdinalIgnoreCase)
                        || (cmd.Contains("opencode", StringComparison.OrdinalIgnoreCase) && cmd.Contains(" serve ", StringComparison.OrdinalIgnoreCase))
                        || (cmd.Contains("openscience", StringComparison.OrdinalIgnoreCase) && cmd.Contains(" serve ", StringComparison.OrdinalIgnoreCase));
                    if (isOurs && !keep.Contains(pid))
                    {
                        try { Process.GetProcessById(pid).Kill(true); } catch { }
                    }
                }
                catch { }
            }
        }
        catch { }
    }
}

/// <summary>Windows Job Object 连坐组：挂 KILL_ON_JOB_CLOSE，壳被强杀时由内核终结所有成员子进程。</summary>
internal static class ChildProcessJob
{
    private const int JobObjectExtendedLimitInformation = 9;
    private const uint JobObjectLimitKillOnJobClose = 0x2000;

    [StructLayout(LayoutKind.Sequential)]
    private struct JobBasicLimitInformation
    {
        public long PerProcessUserTimeLimit;
        public long PerJobUserTimeLimit;
        public uint LimitFlags;
        public UIntPtr MinimumWorkingSetSize;
        public UIntPtr MaximumWorkingSetSize;
        public uint ActiveProcessLimit;
        public UIntPtr Affinity;
        public uint PriorityClass;
        public uint SchedulingClass;
    }

    [StructLayout(LayoutKind.Sequential)]
    private struct JobIoCounters
    {
        public ulong ReadOperationCount, WriteOperationCount, OtherOperationCount;
        public ulong ReadTransferCount, WriteTransferCount, OtherTransferCount;
    }

    [StructLayout(LayoutKind.Sequential)]
    private struct JobExtendedLimitInformation
    {
        public JobBasicLimitInformation BasicLimitInformation;
        public JobIoCounters IoInfo;
        public UIntPtr ProcessMemoryLimit, JobMemoryLimit, PeakProcessMemoryUsed, PeakJobMemoryUsed;
    }

    [DllImport("kernel32.dll", CharSet = CharSet.Unicode)]
    private static extern IntPtr CreateJobObject(IntPtr attributes, string? name);

    [DllImport("kernel32.dll")]
    private static extern bool SetInformationJobObject(IntPtr job, int infoClass, IntPtr info, uint infoLength);

    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern bool AssignProcessToJobObject(IntPtr job, IntPtr process);

    public static IntPtr Create()
    {
        var job = CreateJobObject(IntPtr.Zero, null);
        if (job == IntPtr.Zero) return IntPtr.Zero;
        var info = new JobExtendedLimitInformation();
        info.BasicLimitInformation.LimitFlags = JobObjectLimitKillOnJobClose;
        var size = Marshal.SizeOf<JobExtendedLimitInformation>();
        var ptr = Marshal.AllocHGlobal(size);
        try
        {
            Marshal.StructureToPtr(info, ptr, false);
            SetInformationJobObject(job, JobObjectExtendedLimitInformation, ptr, (uint)size);
        }
        finally
        {
            Marshal.FreeHGlobal(ptr);
        }
        return job;
    }

    public static void Assign(IntPtr job, Process process)
    {
        if (job == IntPtr.Zero) return;
        try { AssignProcessToJobObject(job, process.Handle); } catch { /* 不支持时静默降级为原有清理逻辑 */ }
    }
}
