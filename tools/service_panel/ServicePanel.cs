// Icarus 智测 · 服务开关面板（Windows GUI，单文件 exe）
//
// 为什么要有这个 exe：快捷方式能双击，但"开"和"关"是两个图标，而且**当前是开是关看不出来**——
// 用户只能靠"点了没反应"来推断，而那种反馈和"坏了"没区别。这个面板把状态、开关和日志放进
// 同一个窗口：状态灯常亮，按钮跟着状态启用/禁用，脚本说了什么直接显示在窗口里。
//
// 三条刻意的设计：
//
// 1. **它不做业务逻辑，只调既有的 `start_ui.ps1` / `stop_ui.ps1`。**
//    端口探测、虚拟网卡过滤、Icarus 检查这些规则只有一份，改在脚本里就同时生效；
//    若在这里用 C# 重写一遍，两份实现迟早会不一致，而差异只会在用户机器上暴露。
// 2. **判断"在不在跑"靠轮询健康检查，不靠记住自己启动过什么。**
//    服务可能是别人（命令行、快捷方式、上一次开机）启动的，也可能自己挂了；
//    只有 `/_stcore/health` 能回答这个问题。理由见 `ServiceProbe.IsHealthy`。
// 3. **关窗口前必须问一句。** 服务是独立进程，关掉面板它照样活着，
//    所以"关窗口"和"停服务"是两件事，得让用户明确选一次。
//
// 同一个 exe 也支持命令行：`/start`、`/stop`、`/status`（见 ConsoleMain）。
// 这既是给脚本用的接口，也是**唯一能自动化验证这个 exe 的途径**——
// GUI 按钮点不了，命令行能，于是它的启动/停止路径可以被真实测到。

using System;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.Net;
using System.Runtime.InteropServices;
using System.Text;
using System.Threading;
using System.Windows.Forms;

namespace IcarusPanel
{
    internal static class Program
    {
        [STAThread]
        private static int Main(string[] args)
        {
            if (args.Length > 0 && IsCommand(args[0]))
            {
                return ConsoleMain(args[0]);
            }

            Application.EnableVisualStyles();
            Application.SetCompatibleTextRenderingDefault(false);
            Application.Run(new PanelForm());
            return 0;
        }

        private static bool IsCommand(string arg)
        {
            string name = arg.TrimStart('-', '/').ToLowerInvariant();
            return name == "start" || name == "stop" || name == "status" || name == "help";
        }

        // ------------------------------------------------------------------ 命令行模式

        private static int ConsoleMain(string arg)
        {
            StdHandles.SetUpOutput();

            string name = arg.TrimStart('-', '/').ToLowerInvariant();
            switch (name)
            {
                case "help":
                    Console.WriteLine("用法：IcarusPanel.exe [/start | /stop | /status]");
                    Console.WriteLine("  不带参数   打开控制面板窗口（双击也是这个）");
                    Console.WriteLine("  /start    启动服务，等它就绪后返回");
                    Console.WriteLine("  /stop     停止服务");
                    Console.WriteLine("  /status   打印状态：在跑返回 0，没跑返回 3");
                    return 0;

                case "status":
                    int live = ServiceProbe.FindLivePort(0);
                    if (live > 0)
                    {
                        Console.WriteLine("running http://127.0.0.1:" + live);
                        return 0;
                    }
                    Console.WriteLine("stopped");
                    return 3;

                case "stop":
                    Console.Write(ServiceProbe.RunScript(ServiceProbe.Root, "stop_ui.ps1", ""));
                    bool stillRunning = ServiceProbe.FindLivePort(0) > 0;
                    Console.WriteLine(stillRunning ? "still running" : "stopped");
                    return stillRunning ? 4 : 0;

                default:
                    // -Headless：不打印进度、也不去改控制台标题或收窗口——
                    // 这里用的是**调用者自己的控制台**，改它的标题再把它最小化是在劫持别人的窗口。
                    //
                    // 这里必须用 LaunchDetached 而不是带重定向的 Launch：launcher 会一直活到服务结束，
                    // 它一旦拿到我们的标准输出句柄，调用者的重定向就永远等不到结束（见 LaunchDetached）。
                    string logPath;
                    ServiceProbe.LaunchDetached(ServiceProbe.Root, "start_ui.ps1", " -NoBrowser -Headless", out logPath);

                    int port = ServiceProbe.WaitForHealthy(90);
                    if (port > 0)
                    {
                        Console.WriteLine("running http://127.0.0.1:" + port);
                        return 0;
                    }

                    Console.WriteLine("failed: 等不到健康检查。启动脚本最后的输出：");
                    foreach (string line in ServiceProbe.TailOf(logPath, 12))
                    {
                        Console.WriteLine("  " + line);
                    }
                    return 5;
            }
        }
    }

    /// <summary>
    /// 标准输出/错误句柄的两件事，都只在"被别的程序调用"时才暴露问题，
    /// 所以集中放在一处并写清来由。
    /// </summary>
    internal static class StdHandles
    {
        [DllImport("kernel32.dll")]
        private static extern bool AttachConsole(int processId);

        [DllImport("kernel32.dll")]
        private static extern IntPtr GetStdHandle(int stdHandle);

        [DllImport("kernel32.dll")]
        private static extern uint GetFileType(IntPtr handle);

        [DllImport("kernel32.dll", SetLastError = true)]
        private static extern bool SetHandleInformation(IntPtr handle, uint mask, uint flags);

        private const int StdOutputHandle = -11;
        private const int StdErrorHandle = -12;
        private const int AttachParentProcess = -1;
        private const uint FileTypeUnknown = 0;
        private const uint FileTypeChar = 2;   // 真正的控制台
        private const uint HandleFlagInherit = 0x1;

        private static IntPtr Output()
        {
            return GetStdHandle(StdOutputHandle);
        }

        private static bool Usable(IntPtr handle)
        {
            return handle != IntPtr.Zero && handle != new IntPtr(-1);
        }

        /// <summary>
        /// 决定命令行输出去哪儿、用什么编码。三种情况各有一次真实翻车：
        ///
        /// - **没有标准输出时接父进程的控制台**（GUI 子系统的 exe 双击时就没有）。
        /// - **接到管道/文件时不能去 AttachConsole**：那会让输出绕开管道直接打到控制台，
        ///   调用者（脚本、测试）什么都收不到，看起来就像"命令跑了但没反应"。
        /// - **不是真控制台时必须自己指定 UTF-8**：.NET 的默认输出编码跟着系统代码页走，
        ///   中文机器上是 GBK。实测把 `/help` 重定向到文件，中文全是乱码——
        ///   控制台里看着正常，所以这个问题只在被脚本调用时才暴露。
        /// </summary>
        internal static void SetUpOutput()
        {
            IntPtr stdout = Output();
            uint type = Usable(stdout) ? GetFileType(stdout) : FileTypeUnknown;

            if (type == FileTypeUnknown)
            {
                AttachConsole(AttachParentProcess);
                return;
            }

            if (type == FileTypeChar)
            {
                return;
            }

            try
            {
                // 必须自己包一层 StreamWriter 并**显式**给 UTF-8：
                // `Console.OutputEncoding = ...` 这条路实测无效——被重定向又没有控制台时它设不上，
                // 异常被下面的 catch 吞掉，于是仍然按系统代码页（中文机器上是 GBK）写出去。
                // 症状很有迷惑性：ASCII 部分（`running …`、`stopped`）完全正常，
                // 只有脚本回显的中文变成乱码，所以看日志很容易以为"脚本坏了"。
                StreamWriter writer = new StreamWriter(Console.OpenStandardOutput(), new UTF8Encoding(false));
                writer.AutoFlush = true;
                Console.SetOut(writer);
            }
            catch
            {
                // 设不了就退回默认编码：ASCII 部分仍然是对的
            }
        }

        /// <summary>
        /// 别让子进程继承**我们自己的**标准输出/错误句柄。
        ///
        /// 不是洁癖，是实测踩到的坑：调用者写 `IcarusPanel.exe /start > log.txt` 时，
        /// 那个管道归调用者所有，而我们启动的子进程（start_ui.ps1）会一直活到服务结束。
        /// 它一旦继承了这个句柄，调用者的重定向就**永远等不到结束**——表现为"命令卡死"，
        /// 尽管我们的 exe 早就打印完结果退出了。
        /// 实测症状：/start 已经打印 `running http://127.0.0.1:8501`，而 PowerShell 等了 120 秒。
        ///
        /// 子进程自己的 stdout 不受影响：.NET 会新建管道并把它显式写进 STARTUPINFO。
        /// </summary>
        internal static void DetachInheritedStdHandles()
        {
            int[] which = new int[] { StdOutputHandle, StdErrorHandle };
            for (int index = 0; index < which.Length; index++)
            {
                IntPtr handle = GetStdHandle(which[index]);
                if (Usable(handle))
                {
                    SetHandleInformation(handle, HandleFlagInherit, 0);
                }
            }
        }
    }

    /// <summary>
    /// 与 `start_ui.ps1` / `stop_ui.ps1` 打交道的那一层。
    /// 单独抽出来是刻意的：GUI 与命令行两条路径共用它，于是"面板能启动"和"命令行能启动"
    /// 不可能出现两套行为。
    /// </summary>
    internal static class ServiceProbe
    {
        private const int FirstPort = 8501;
        private const int PortWindow = 10;

        //: 单次探测的超时。**实测这台机器上连一个没人监听的环回端口不是立刻被拒，
        //: 而是等到超时**——10 个端口 × 400ms 让"已停止"这个状态要 5.2 秒才出得来。
        //: 150ms 对本地健康检查足够（服务在跑时通常几毫秒就返回）。
        private const int ProbeTimeoutMs = 150;

        //: 首选端口失败后再慢试一次：服务刚启动或正忙时偶尔会慢一拍，
        //: 因为一次慢响应就把状态灯从"运行中"翻成"已停止"，用户会以为服务挂了。
        private const int SlowProbeTimeoutMs = 800;

        private static string _root;

        internal static string Root
        {
            get { return LocateRoot(); }
        }

        private static string LocateRoot()
        {
            if (_root != null)
            {
                return _root;
            }

            // exe 就放在仓库根。允许它被挪走（比如复制到桌面），所以再往上找几层：
            // 找到有 start_ui.ps1 的那一层才算仓库根。
            DirectoryInfo dir = new DirectoryInfo(Application.StartupPath);
            for (int depth = 0; dir != null && depth < 5; depth++)
            {
                if (File.Exists(Path.Combine(dir.FullName, "start_ui.ps1")))
                {
                    _root = dir.FullName;
                    return _root;
                }
                dir = dir.Parent;
            }

            _root = Application.StartupPath;
            return _root;
        }

        // -------------------------------------------------------------- 健康检查

        /// <summary>
        /// 端口上是不是**我们**的服务。
        /// 只看"端口有人监听"不够：8501 上可能是别的程序，那样面板会显示"运行中"却打不开页面。
        /// 所以认 Streamlit 的健康检查端点，和 `stop_ui.ps1` 用的是同一个判据。
        /// </summary>
        internal static bool IsHealthy(int port)
        {
            return IsHealthy(port, ProbeTimeoutMs);
        }

        internal static bool IsHealthy(int port, int timeoutMs)
        {
            try
            {
                HttpWebRequest request = (HttpWebRequest)WebRequest.Create(
                    "http://127.0.0.1:" + port + "/_stcore/health");
                request.Method = "GET";
                request.Timeout = timeoutMs;
                request.ReadWriteTimeout = timeoutMs;
                request.Proxy = null;   // 走环回地址，别让系统代理插一脚

                using (HttpWebResponse response = (HttpWebResponse)request.GetResponse())
                {
                    return response.StatusCode == HttpStatusCode.OK;
                }
            }
            catch
            {
                return false;
            }
        }

        /// <summary>在 8501 起的 10 个端口里找活着的实例；<paramref name="preferred"/> 先试。</summary>
        internal static int FindLivePort(int preferred)
        {
            if (preferred > 0)
            {
                if (IsHealthy(preferred, ProbeTimeoutMs) || IsHealthy(preferred, SlowProbeTimeoutMs))
                {
                    return preferred;
                }
            }

            for (int offset = 0; offset < PortWindow; offset++)
            {
                int port = FirstPort + offset;
                if (port != preferred && IsHealthy(port, ProbeTimeoutMs))
                {
                    return port;
                }
            }

            return 0;
        }

        /// <summary>等它真的就绪：脚本自己也会等，这里兜住"端口被占而自动换端口"的情况。</summary>
        internal static int WaitForHealthy(int timeoutSeconds)
        {
            DateTime deadline = DateTime.Now.AddSeconds(timeoutSeconds);
            while (DateTime.Now < deadline)
            {
                int port = FindLivePort(0);
                if (port > 0)
                {
                    return port;
                }
                Thread.Sleep(600);
            }
            return 0;
        }

        // -------------------------------------------------------------- 调脚本

        internal static ProcessStartInfo BuildStartInfo(string root, string scriptName, string extraArgs)
        {
            string script = Path.Combine(root, scriptName);
            ProcessStartInfo info = new ProcessStartInfo("powershell");
            info.WorkingDirectory = root;
            info.UseShellExecute = false;
            info.CreateNoWindow = true;
            info.RedirectStandardOutput = true;
            info.RedirectStandardError = true;
            info.StandardOutputEncoding = Encoding.UTF8;
            info.StandardErrorEncoding = Encoding.UTF8;
            // `[Console]::OutputEncoding` 这一句是必需的：PowerShell 5.1 往管道写的时候
            // 默认按 OEM 代码页（中文机器上是 GBK），不设就是一堆乱码。
            info.Arguments =
                "-NoProfile -ExecutionPolicy Bypass -Command \"" +
                "[Console]::OutputEncoding=[System.Text.Encoding]::UTF8; & '" +
                script + "'" + extraArgs + "\"";
            return info;
        }

        /// <summary>
        /// 启动脚本后**立刻返回**，不等待：`start_ui.ps1` 会在服务运行期间一直挂着，
        /// 等它就等于把面板冻住。
        ///
        /// 两个回调都必须在这里挂上再 Start——`BeginOutputReadLine` 之后才挂处理器的话，
        /// 最早到达的几行会在没人接的时候被丢掉，而那几行往往正是"为什么起不来"。
        /// </summary>
        internal static Process Launch(
            string root, string scriptName, string extraArgs,
            Action<string> onLine, Action<int> onExit)
        {
            string script = Path.Combine(root, scriptName);
            if (!File.Exists(script))
            {
                if (onLine != null)
                {
                    onLine("找不到脚本：" + script);
                }
                if (onExit != null)
                {
                    onExit(-1);
                }
                return null;
            }

            Process process = new Process();
            process.StartInfo = BuildStartInfo(root, scriptName, extraArgs);

            // 在 Start 之前断开继承，见 StdHandles.DetachInheritedStdHandles 的说明。
            StdHandles.DetachInheritedStdHandles();

            if (onLine != null)
            {
                process.OutputDataReceived += delegate(object sender, DataReceivedEventArgs e)
                {
                    if (e.Data != null)
                    {
                        onLine(e.Data);
                    }
                };
                process.ErrorDataReceived += delegate(object sender, DataReceivedEventArgs e)
                {
                    if (e.Data != null)
                    {
                        onLine(e.Data);
                    }
                };
            }

            if (onExit != null)
            {
                process.EnableRaisingEvents = true;
                process.Exited += delegate
                {
                    int code = 0;
                    try
                    {
                        code = process.ExitCode;
                    }
                    catch
                    {
                        // 拿不到退出码就算了，调用方自己还会看状态
                    }
                    onExit(code);
                };
            }

            process.Start();
            // 必须把管道读干：不读的话子进程写满 4KB 缓冲区就会卡死。
            process.BeginOutputReadLine();
            process.BeginErrorReadLine();
            return process;
        }

        /// <summary>
        /// 启动一个**会一直活下去**的子进程，并且**绝不碰调用者的标准输出**。
        ///
        /// 为什么要单独有这一条路：launcher（`start_ui.ps1`）会一直活到服务结束。
        /// 如果它继承了调用者的标准输出句柄，调用者的重定向/管道就永远等不到结束——
        /// 表现为"命令卡死"，尽管我们的 exe 早就打印完结果退出了。实测症状：
        /// `IcarusPanel.exe /start | Out-File log.txt` 打印出了 `running http://…`，
        /// 而 PowerShell 等了 120 秒还没返回。
        ///
        /// 做法是交给 `cmd` 做重定向：输出落到一个临时文件，句柄归 cmd 所有，
        /// 我们和调用者的标准输出都不掺和。顺带还能把这个文件当作**失败原因**——
        /// 光说"启动失败"而说不出为什么，和没有报错差不多。
        /// </summary>
        internal static void LaunchDetached(string root, string scriptName, string extraArgs, out string logPath)
        {
            logPath = Path.Combine(Path.GetTempPath(), "icarus-panel-start.log");

            string script = Path.Combine(root, scriptName);
            // 整个命令**不加外层引号**：cmd 的 /c 在首字符是引号时会做"剥引号"的特例处理，
            // 而里面的 `-File "路径"` 必须原样传下去。命令以 powershell 开头就没有这个问题。
            string arguments =
                "/c powershell -NoProfile -ExecutionPolicy Bypass -File \"" + script + "\"" + extraArgs +
                " > \"" + logPath + "\" 2>&1";

            ProcessStartInfo info = new ProcessStartInfo("cmd.exe");
            info.Arguments = arguments;
            info.WorkingDirectory = root;
            info.UseShellExecute = true;                                // 关键：不继承我们的句柄
            info.WindowStyle = ProcessWindowStyle.Hidden;               // 关键：不弹黑窗口
            Process.Start(info);
        }

        /// <summary>读一个文本文件的最后几行（用于把启动失败的原因带给用户）。</summary>
        internal static string[] TailOf(string path, int lines)
        {
            try
            {
                if (!File.Exists(path))
                {
                    return new string[] { "（没有日志：" + path + "）" };
                }

                string[] all = File.ReadAllLines(path);
                int start = Math.Max(0, all.Length - lines);
                string[] tail = new string[all.Length - start];
                Array.Copy(all, start, tail, 0, tail.Length);
                return tail;
            }
            catch (Exception error)
            {
                return new string[] { "（读日志失败：" + error.Message + "）" };
            }
        }

        /// <summary>同步跑一个会自己退出的脚本（`stop_ui.ps1`）并返回它的输出。</summary>
        internal static string RunScript(string root, string scriptName, string extraArgs)
        {
            string script = Path.Combine(root, scriptName);
            if (!File.Exists(script))
            {
                return "找不到脚本：" + script + Environment.NewLine;
            }

            ProcessStartInfo info = BuildStartInfo(root, scriptName, extraArgs);
            StdHandles.DetachInheritedStdHandles();
            using (Process process = Process.Start(info))
            {
                string output = process.StandardOutput.ReadToEnd() + process.StandardError.ReadToEnd();
                process.WaitForExit(20000);
                return output;
            }
        }
    }

    // ---------------------------------------------------------------------- 面板窗口

    internal sealed class PanelForm : Form
    {
        private static readonly Color Ink = Color.FromArgb(13, 27, 36);
        private static readonly Color Cyan = Color.FromArgb(0, 163, 180);
        private static readonly Color Slate = Color.FromArgb(70, 88, 106);
        private static readonly Color Amber = Color.FromArgb(214, 150, 30);
        private static readonly Color Muted = Color.FromArgb(128, 138, 148);
        private static readonly Color Paper = Color.FromArgb(232, 238, 242);

        //: 禁用态的画法。必须自己画：`FlatStyle.Flat` + 自定义 BackColor 的按钮，
        //: 禁用时 WinForms 只把文字变灰、底色照旧，于是"运行中"的「启动服务」看起来和
        //: 可点时一模一样——实测截图对比才发现。而"看不出当前是开是关"正是做这个面板的原因。
        private static readonly Color DisabledBack = Color.FromArgb(228, 233, 237);
        private static readonly Color DisabledFore = Color.FromArgb(152, 160, 168);

        private readonly Label _title = new Label();
        private readonly Panel _dot = new Panel();
        private readonly Label _status = new Label();
        private readonly Label _hint = new Label();
        private readonly Button _start = new Button();
        private readonly Button _stop = new Button();
        private readonly Button _open = new Button();
        private readonly TextBox _log = new TextBox();

        private volatile int _livePort;
        private volatile bool _starting;
        private volatile bool _stopping;
        private volatile bool _closing;
        private bool _scriptsMissing;
        private DateTime _startingSince = DateTime.MinValue;

        internal PanelForm()
        {
            BuildLayout();

            string root = ServiceProbe.Root;
            Text = "Icarus 智测 · 服务开关";
            if (!File.Exists(Path.Combine(root, "start_ui.ps1")))
            {
                _scriptsMissing = true;
                Log("找不到 start_ui.ps1（找的是 " + root + "）。请把面板放回项目目录再运行。");
            }
            else
            {
                Log("项目目录：" + root);
                Log("状态每 1.2 秒自动刷新一次。");
            }
        }

        private void BuildLayout()
        {
            SuspendLayout();

            ClientSize = new Size(470, 372);
            FormBorderStyle = FormBorderStyle.FixedSingle;
            MaximizeBox = false;
            StartPosition = FormStartPosition.CenterScreen;
            BackColor = Color.White;
            Font = new Font("Microsoft YaHei UI", 9F);

            try
            {
                Icon = Icon.ExtractAssociatedIcon(Application.ExecutablePath);
            }
            catch
            {
                // 拿不到图标不该让面板起不来
            }

            _title.Text = "Icarus 智测";
            _title.Font = new Font("Microsoft YaHei UI", 14F, FontStyle.Bold);
            _title.ForeColor = Ink;
            _title.SetBounds(18, 14, 420, 30);

            _dot.SetBounds(20, 56, 14, 14);
            _dot.BackColor = Muted;

            _status.Font = new Font("Microsoft YaHei UI", 10F);
            _status.ForeColor = Ink;
            _status.SetBounds(42, 52, 410, 22);
            _status.Text = "正在检查…";

            _hint.ForeColor = Muted;
            _hint.SetBounds(42, 76, 412, 20);
            _hint.Text = "点「启动服务」，就绪后这里会显示地址。";

            StyleButton(_start, "启动服务", Cyan, Color.White, 18, 104, 138);
            _start.Click += OnStartClick;

            StyleButton(_stop, "停止服务", Slate, Color.White, 164, 104, 138);
            _stop.Click += OnStopClick;

            StyleButton(_open, "打开网页", Paper, Ink, 310, 104, 142);
            _open.Click += OnOpenClick;

            // 初始按钮状态要**显式**设成"还没发现有服务在跑"：
            // WinForms 的默认值是三个按钮全部可用，而第一次探测要花几秒
            // （要扫 10 个端口），那几秒里「停止服务」「打开网页」看着能点、点了没反应。
            SetState(_stop, false, Slate, Color.White);
            SetState(_open, false, Paper, Ink);

            Label logLabel = new Label();
            logLabel.Text = "脚本日志（启动/停止每一步的结果）";
            logLabel.ForeColor = Muted;
            logLabel.SetBounds(18, 150, 300, 18);

            _log.Multiline = true;
            _log.ReadOnly = true;
            _log.ScrollBars = ScrollBars.Vertical;
            _log.BackColor = Ink;
            _log.ForeColor = Color.FromArgb(226, 240, 245);
            _log.Font = new Font("Consolas", 8.5F);
            _log.SetBounds(18, 170, 434, 184);
            _log.TabStop = false;

            Controls.AddRange(new Control[] { _title, _dot, _status, _hint, _start, _stop, _open, logLabel, _log });

            ResumeLayout(false);
        }

        private static void StyleButton(Button button, string text, Color back, Color fore, int x, int y, int width)
        {
            button.Text = text;
            button.SetBounds(x, y, width, 36);
            button.FlatStyle = FlatStyle.Flat;
            button.FlatAppearance.BorderSize = 0;
            button.BackColor = back;
            button.ForeColor = fore;
            button.Font = new Font("Microsoft YaHei UI", 10F);
            button.UseVisualStyleBackColor = false;
        }

        /// <summary>设置按钮可用性，并让它**看起来**就是那个状态（见 DisabledBack 的说明）。</summary>
        private static void SetState(Button button, bool enabled, Color back, Color fore)
        {
            button.Enabled = enabled;
            button.BackColor = enabled ? back : DisabledBack;
            button.ForeColor = enabled ? fore : DisabledFore;
        }

        protected override void OnShown(EventArgs e)
        {
            base.OnShown(e);

            // 单独一个后台线程做轮询：健康检查要发 HTTP 请求，放在 UI 线程上会让窗口卡住，
            // 而"点一下窗口就白掉"正是用户以为程序挂了的时刻。
            Thread watcher = new Thread(WatchLoop);
            watcher.IsBackground = true;
            watcher.Start();
        }

        private void WatchLoop()
        {
            while (!_closing)
            {
                int port = ServiceProbe.FindLivePort(_livePort);

                // 单次失败不改口：探针超时可能只是服务忙（150ms/800ms 两次都赶上它忙的时候）。
                // 立刻再确认一次，而不是等下一轮——一轮要 1.2 秒，用户会看到状态灯"卡"在旧状态上。
                // 这条是实测踩出来的：状态灯已经写着「已停止」，而 `/_stcore/health` 仍返回 200，
                // 一个会撒谎的状态灯比没有状态灯更糟——用户会去重启一个正在跑的服务。
                if (port == 0 && !_closing)
                {
                    Thread.Sleep(400);
                    port = ServiceProbe.FindLivePort(_livePort);
                }

                if (_closing)
                {
                    return;
                }

                try
                {
                    BeginInvoke(new Action<int>(ApplyStatus), port);
                }
                catch (InvalidOperationException)
                {
                    return;   // 窗口已经销毁
                }
                Thread.Sleep(1200);
            }
        }

        /// <summary>
        /// 把一段操弄界面的代码送回 UI 线程执行。
        /// 必须这么做：脚本退出回调来自线程池线程，在那里碰控件轻则抛
        /// `InvalidOperationException`（跨线程访问），重则**静默不生效**——
        /// 实测就出现过"服务已经停了，面板还写着运行中"，于是关窗口时多弹了一个确认框。
        /// </summary>
        private void OnUi(Action action)
        {
            if (_closing || !IsHandleCreated)
            {
                return;
            }

            try
            {
                if (InvokeRequired)
                {
                    BeginInvoke(action);
                }
                else
                {
                    action();
                }
            }
            catch (InvalidOperationException)
            {
                // 窗口正在销毁
            }
        }

        private void ApplyStatus(int port)
        {
            _livePort = port;

            // 「正在停止…」要排在"探测到端口还活着"前面：
            // 停止脚本自己要先扫端口再结束进程（实测约 6~9 秒），这期间端口当然还是活的。
            // 先判 port > 0 的话，用户按下停止后看到的状态**一直是「运行中」**，
            // 直到脚本结束才跳变——那几秒里他不知道按钮到底有没有生效。
            if (_stopping)
            {
                _dot.BackColor = Amber;
                _status.Text = "正在停止…";
                _hint.Text = "stop_ui.ps1 正在按端口找进程，稍等一下。";
                SetState(_start, false, Cyan, Color.White);
                SetState(_stop, false, Slate, Color.White);
                SetState(_open, false, Paper, Ink);
                return;
            }

            if (port > 0)
            {
                _starting = false;
                _dot.BackColor = Cyan;
                _status.Text = "运行中 · http://127.0.0.1:" + port;
                _hint.Text = "关掉这个窗口不会停服务；关之前会再问你一次。";
                SetState(_start, false, Cyan, Color.White);
                SetState(_stop, true, Slate, Color.White);
                SetState(_open, true, Paper, Ink);
                return;
            }

            bool waiting = _starting && (DateTime.Now - _startingSince).TotalSeconds < 90;
            if (!waiting)
            {
                _starting = false;
            }

            _dot.BackColor = waiting ? Amber : Muted;
            _status.Text = waiting ? "正在启动…（第一次要等几秒）" : "已停止";
            _hint.Text = waiting
                ? "下面日志里有每一步的结果。"
                : "点「启动服务」，或双击桌面上的快捷方式。";
            SetState(_start, !waiting && !_scriptsMissing, Cyan, Color.White);
            SetState(_stop, false, Slate, Color.White);
            SetState(_open, false, Paper, Ink);
        }

        // -------------------------------------------------------------- 三个按钮

        private void OnStartClick(object sender, EventArgs e)
        {
            if (_livePort > 0)
            {
                OpenPage();
                return;
            }

            _starting = true;
            _startingSince = DateTime.Now;
            ApplyStatus(0);
            Log("启动服务：调用 start_ui.ps1（端口选择、Icarus 检查都由它负责）");

            ServiceProbe.Launch(
                ServiceProbe.Root, "start_ui.ps1", "-NoBrowser",
                Log,
                delegate(int code)
                {
                    // start_ui.ps1 在服务运行期间一直挂着，所以它退出＝服务结束了。
                    if (code == 0)
                    {
                        Log("（start_ui.ps1 退出：服务已结束）");
                    }
                    else
                    {
                        _starting = false;
                        OnUi(delegate
                        {
                            Log("（start_ui.ps1 退出，退出码 " + code + "：启动没成功，原因在上面）");
                            ApplyStatus(ServiceProbe.FindLivePort(0));
                        });
                    }
                });
        }

        private void OnStopClick(object sender, EventArgs e)
        {
            _starting = false;
            _stopping = true;
            ApplyStatus(_livePort);
            Log("停止服务：调用 stop_ui.ps1（它按端口找进程，不会误杀别的 Python）");
            ServiceProbe.Launch(
                ServiceProbe.Root, "stop_ui.ps1", "",
                Log,
                delegate(int code)
                {
                    // 脚本退出才算停完：这之前状态一直显示「正在停止…」。
                    _stopping = false;
                    OnUi(delegate
                    {
                        ApplyStatus(ServiceProbe.FindLivePort(0));
                        Log(code == 0 ? "（stop_ui.ps1 退出：已停止）" : "（stop_ui.ps1 退出，退出码 " + code + "）");
                    });
                });
        }

        private void OnOpenClick(object sender, EventArgs e)
        {
            OpenPage();
        }

        private void OpenPage()
        {
            if (_livePort <= 0)
            {
                return;
            }
            try
            {
                Process.Start("http://127.0.0.1:" + _livePort);
            }
            catch (Exception error)
            {
                Log("打不开浏览器：" + error.Message);
            }
        }

        // -------------------------------------------------------------- 日志

        private void Log(string line)
        {
            if (_closing)
            {
                return;
            }

            if (InvokeRequired)
            {
                try
                {
                    BeginInvoke(new Action<string>(Log), line);
                }
                catch (InvalidOperationException)
                {
                    // 窗口正在销毁，丢掉这行即可
                }
                return;
            }

            _log.AppendText(DateTime.Now.ToString("HH:mm:ss") + "  " + line + Environment.NewLine);

            // 不设上限的话，长时间运行会把内存吃满（每次刷新都可能追加一行）。
            const int keepChars = 40000;
            if (_log.TextLength > keepChars * 2)
            {
                _log.Text = _log.Text.Substring(_log.TextLength - keepChars);
            }

            _log.SelectionStart = _log.TextLength;
            _log.ScrollToCaret();
        }

        // -------------------------------------------------------------- 关窗口

        protected override void OnFormClosing(FormClosingEventArgs e)
        {
            if (_livePort > 0)
            {
                // 服务是独立进程，关掉面板它照样活着。所以这里必须问一次：
                // "关窗口＝关服务"是最常见的误解，而误解的代价是服务在后台一直占着端口。
                DialogResult answer = MessageBox.Show(
                    this,
                    "服务还在运行：http://127.0.0.1:" + _livePort + Environment.NewLine + Environment.NewLine +
                    "要顺便停掉它吗？" + Environment.NewLine +
                    "选「否」则服务继续在后台运行，下次打开面板还是这个状态。",
                    "Icarus 智测 · 服务开关",
                    MessageBoxButtons.YesNoCancel,
                    MessageBoxIcon.Question);

                if (answer == DialogResult.Cancel)
                {
                    e.Cancel = true;
                    return;
                }

                if (answer == DialogResult.Yes)
                {
                    ServiceProbe.RunScript(ServiceProbe.Root, "stop_ui.ps1", "");
                }
            }

            _closing = true;
            base.OnFormClosing(e);
        }
    }
}
