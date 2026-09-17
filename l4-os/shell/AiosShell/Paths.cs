using System;
using System.Collections.Generic;
using System.IO;

namespace AiosShell;

/// <summary>
/// 统一路径解析（开源可移植）：环境变量 > config.json["paths"] > 仓库相对默认。
/// 与 l2-memory/scripts/paths.py 同契约（AIOS_* 环境变量；config.json 由两侧共同消费）。
/// 仓库根探测：环境变量 AIOS_ROOT，或从程序位置向上找含 l2-memory 的目录。
/// 注意：config.json 在进程启动时读取一次；改配置后需重启壳生效。
/// </summary>
internal static class Paths
{
    public static readonly string Root = FindRoot();
    private static readonly IReadOnlyDictionary<string, string> Cfg = LoadConfigPaths(Root);
    public static readonly string Vault = Pick("AIOS_VAULT", "vault") ?? Path.Combine(Root, "vault");
    public static readonly string Python = Pick("AIOS_PYTHON", "python") ?? "python";
    public static readonly string Node = Pick("AIOS_NODE", "node") ?? "node";
    public static readonly string OpencodeExe = Pick("AIOS_OPENCODE_EXE", "opencode_exe") ?? "opencode";
    public static readonly string OpenScienceJs = Pick("AIOS_OPENSCIENCE_JS", "openscience_js") ?? "openscience";
    public static readonly string LoopxCmd = Pick("AIOS_LOOPX_EXE", "loopx_exe") ?? "loopx";

    public static readonly string RuntimeRoot = Path.Combine(Root, ".loopx-runtime");
    public static readonly string ChatScript = Path.Combine(Root, "l4-os", "scripts", "serve_chat.py");
    public static readonly string BuildGraphDataPy = Path.Combine(Root, "l4-os", "scripts", "build_graph_data.py");
    public static readonly string WfctlPy = Path.Combine(Root, "l2-memory", "workflows", "wfctl.py");
    public static readonly string DashboardDist = Path.Combine(Root, "l4-os", "dashboard", "dist");

    private static string? Env(string key) => Environment.GetEnvironmentVariable(key);

    /** 同 paths.py：环境变量 > config.json["paths"] > null */
    private static string? Pick(string envKey, string cfgKey)
    {
        var v = Env(envKey);
        if (!string.IsNullOrWhiteSpace(v)) return v;
        return Cfg.TryGetValue(cfgKey, out var c) && !string.IsNullOrWhiteSpace(c) ? c : null;
    }

    /** 读 l2-memory/config.json 的 paths 段（缺失/损坏 → 空表，不阻塞）。 */
    private static IReadOnlyDictionary<string, string> LoadConfigPaths(string root)
    {
        var map = new Dictionary<string, string>();
        try
        {
            var file = Path.Combine(root, "l2-memory", "config.json");
            if (!File.Exists(file)) return map;
            using var doc = System.Text.Json.JsonDocument.Parse(File.ReadAllText(file));
            if (!doc.RootElement.TryGetProperty("paths", out var section)) return map;
            foreach (var prop in section.EnumerateObject())
            {
                if (prop.Value.ValueKind != System.Text.Json.JsonValueKind.String) continue;
                var val = prop.Value.GetString();
                if (!string.IsNullOrWhiteSpace(val)) map[prop.Name] = val!;
            }
        }
        catch
        {
            // 与 Python 侧一致：配置缺失/损坏时静默回落默认值
        }
        return map;
    }

    private static string FindRoot()
    {
        var fromEnv = Env("AIOS_ROOT");
        if (!string.IsNullOrEmpty(fromEnv)) return fromEnv!;
        var dir = new DirectoryInfo(AppContext.BaseDirectory);
        while (dir != null)
        {
            if (Directory.Exists(Path.Combine(dir.FullName, "l2-memory")))
                return dir.FullName;
            dir = dir.Parent;
        }
        return AppContext.BaseDirectory;
    }
}
