using System;
using System.IO;

namespace AiosShell;

/// <summary>
/// 统一路径解析（开源可移植）：环境变量 > 仓库相对默认。
/// 与 l2-memory/scripts/paths.py 同契约（AIOS_* 环境变量，config.json["paths"] 由 Python 侧消费）。
/// 仓库根探测：环境变量 AIOS_ROOT，或从程序位置向上找含 l2-memory 的目录。
/// </summary>
internal static class Paths
{
    public static readonly string Root = FindRoot();
    public static readonly string Vault = Env("AIOS_VAULT") ?? Path.Combine(Root, "vault");
    public static readonly string Python = Env("AIOS_PYTHON") ?? "python";
    public static readonly string Node = Env("AIOS_NODE") ?? "node";
    public static readonly string OpencodeExe = Env("AIOS_OPENCODE_EXE") ?? "opencode";
    public static readonly string OpenScienceJs = Env("AIOS_OPENSCIENCE_JS") ?? "openscience";
    public static readonly string LoopxCmd = Env("AIOS_LOOPX_EXE") ?? "loopx";

    public static readonly string RuntimeRoot = Path.Combine(Root, ".loopx-runtime");
    public static readonly string ChatScript = Path.Combine(Root, "l4-os", "scripts", "serve_chat.py");
    public static readonly string BuildGraphDataPy = Path.Combine(Root, "l4-os", "scripts", "build_graph_data.py");
    public static readonly string WfctlPy = Path.Combine(Root, "l2-memory", "workflows", "wfctl.py");
    public static readonly string DashboardDist = Path.Combine(Root, "l4-os", "dashboard", "dist");

    private static string? Env(string key) => Environment.GetEnvironmentVariable(key);

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
