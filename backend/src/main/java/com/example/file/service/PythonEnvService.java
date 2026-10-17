package com.example.file.service;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.core.conditions.update.LambdaUpdateWrapper;
import com.example.file.common.BizException;
import com.example.file.entity.PythonEnv;
import com.example.file.mapper.PythonEnvMapper;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ArrayNode;
import com.fasterxml.jackson.databind.node.ObjectNode;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.context.event.ApplicationReadyEvent;
import org.springframework.context.event.EventListener;
import org.springframework.core.io.ClassPathResource;
import org.springframework.stereotype.Service;

import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.IOException;
import java.io.InputStream;
import java.nio.charset.Charset;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.time.LocalDateTime;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.Comparator;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Set;
import java.util.concurrent.TimeUnit;
import java.util.regex.Pattern;

/**
 * Python 环境选择与检测。
 * <p>
 * 检测由本 Java 服务完成：用被选中的 python.exe 执行 classpath 中的 python/env_probe.py（只依赖标准库），
 * 解析其输出的 JSON；因此后端本身不依赖用户所选的 Python。检测通过（OK / WARN）的配置写入 python_env 表，
 * 并写出 python-service/.python-env（一行 python.exe 路径，GBK 编码，供 start.bat 的 set /p 读取），
 * 下次启动自动使用。
 */
@Service
public class PythonEnvService {

    private static final Logger log = LoggerFactory.getLogger(PythonEnvService.class);

    private static final boolean WINDOWS = System.getProperty("os.name", "").toLowerCase(Locale.ROOT).contains("win");
    /** Windows 控制台程序（where 等）的输出编码，中文系统为 GBK */
    private static final Charset NATIVE = Charset.forName(System.getProperty("native.encoding", Charset.defaultCharset().name()));
    private static final Pattern PYTHON_EXE = Pattern.compile(WINDOWS ? "(?i)^pythonw?(\\d+(\\.\\d+)*)?\\.exe$" : "^python(\\d+(\\.\\d+)*)?$");
    private static final String PROBE_MARK = "@@PROBE@@";
    private static final String MINICONDA_OFFICIAL = "https://docs.conda.io/en/latest/miniconda.html";
    private static final String MINICONDA_TUNA = "https://mirrors.tuna.tsinghua.edu.cn/anaconda/miniconda/";

    private final PythonEnvMapper mapper;
    private final ObjectMapper objectMapper;
    private final Path projectRoot;
    private final int[] minVersion;
    private final String minVersionText;

    public PythonEnvService(PythonEnvMapper mapper,
                            ObjectMapper objectMapper,
                            @Value("${python-env.project-root:}") String projectRoot,
                            @Value("${python-env.min-version:3.10}") String minVersion) {
        this.mapper = mapper;
        this.objectMapper = objectMapper;
        this.projectRoot = resolveProjectRoot(projectRoot);
        this.minVersionText = minVersion;
        this.minVersion = Arrays.stream(minVersion.split("\\.")).mapToInt(Integer::parseInt).toArray();
        log.info("Python 环境检测：项目根目录 {}", this.projectRoot);
    }

    /** 未配置时自动判断：从 backend/ 启动则为上级目录，从项目根启动则为当前目录 */
    private static Path resolveProjectRoot(String configured) {
        if (configured != null && !configured.isBlank()) {
            return Paths.get(configured).toAbsolutePath().normalize();
        }
        Path cwd = Paths.get("").toAbsolutePath().normalize();
        if (Files.isDirectory(cwd.resolve("python-service"))) {
            return cwd;
        }
        Path parent = cwd.getParent();
        return parent != null && Files.isDirectory(parent.resolve("python-service")) ? parent : cwd;
    }

    private Path serviceDir() {
        return projectRoot.resolve("python-service");
    }

    /** 启动时按当前生效配置重写 .python-env，保证 start.bat 读到的与数据库一致 */
    @EventListener(ApplicationReadyEvent.class)
    public void syncEnvFile() {
        PythonEnv active = findActive();
        if (active != null) {
            writeEnvFile(active.getPythonPath());
        }
    }

    // ------------------------------------------------------------------ 发现

    /**
     * 汇总可选项：PATH 上的 python、Conda 安装、项目 venv 默认路径、当前配置；anyUsable=false 时前端展示 Miniconda 安装指引。
     */
    public Map<String, Object> discover() {
        List<Map<String, Object>> system = findSystemPythons();
        Map<String, Object> conda = condaEnvs(null);
        Map<String, Object> venv = defaultVenv();
        boolean anyUsable = system.stream().anyMatch(p -> !Boolean.TRUE.equals(p.get("stub")))
                || Boolean.TRUE.equals(conda.get("found"))
                || Boolean.TRUE.equals(venv.get("exists"));

        Map<String, Object> out = new LinkedHashMap<>();
        out.put("projectRoot", projectRoot.toString());
        out.put("minVersion", minVersionText);
        out.put("system", system);
        out.put("conda", conda);
        out.put("venv", venv);
        out.put("anyUsable", anyUsable);
        out.put("miniconda", minicondaGuide());
        out.put("current", current());
        return out;
    }

    private List<Map<String, Object>> findSystemPythons() {
        List<String> cmd = WINDOWS ? List.of("where", "python") : List.of("which", "-a", "python3", "python");
        Exec r = exec(cmd, 10, NATIVE, null);
        Set<String> paths = new LinkedHashSet<>();
        for (String line : r.output.split("\\R")) {
            if (!line.isBlank() && Files.isRegularFile(Paths.get(line.trim()))) {
                paths.add(line.trim());
            }
        }
        List<Map<String, Object>> out = new ArrayList<>();
        for (String p : paths) {
            boolean stub = isStoreStub(p);
            Map<String, Object> item = new LinkedHashMap<>();
            item.put("path", p);
            item.put("stub", stub);
            // 应用商店占位程序运行会弹出商店，不执行
            item.put("version", stub ? null : quickVersion(p));
            out.add(item);
        }
        return out;
    }

    private static boolean isStoreStub(String path) {
        return path.toLowerCase(Locale.ROOT).replace('/', '\\').contains("\\microsoft\\windowsapps\\");
    }

    private String quickVersion(String python) {
        Exec r = exec(List.of(python, "--version"), 8, NATIVE, null);
        String v = r.output.trim();
        return r.exitCode == 0 && v.startsWith("Python ") ? v.substring(7) : null;
    }

    private Map<String, Object> defaultVenv() {
        // 本项目的 venv 在 python-service/.venv；兼容放在项目根的 .venv
        List<Path> candidates = List.of(serviceDir().resolve(".venv"), projectRoot.resolve(".venv"));
        Path chosen = candidates.stream().filter(Files::isDirectory).findFirst().orElse(candidates.get(0));
        Path python = WINDOWS ? chosen.resolve("Scripts").resolve("python.exe") : chosen.resolve("bin").resolve("python");
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("venvDir", chosen.toString());
        out.put("path", python.toString());
        out.put("exists", Files.isRegularFile(python));
        out.put("createCommand", "py -3.10 -m venv \"" + chosen + "\"");
        return out;
    }

    /**
     * 列出 Conda 环境。condaPath 可为 Conda 安装目录或 conda.exe / conda.bat；为空时自动查找
     * （CONDA_EXE 环境变量 → PATH 上的 conda → 常见安装目录）。
     */
    public Map<String, Object> condaEnvs(String condaPath) {
        Map<String, Object> out = new LinkedHashMap<>();
        Path root = condaPath == null || condaPath.isBlank() ? findCondaRoot() : condaRootFrom(Paths.get(condaPath.trim()));
        if (root == null) {
            out.put("found", false);
            out.put("message", condaPath == null || condaPath.isBlank()
                    ? "未找到 Conda（PATH、CONDA_EXE 和常见安装目录中都没有），请手动填写 Conda 安装目录"
                    : "该路径下没有找到 conda（应为 Miniconda/Anaconda 安装目录，或其中的 Scripts\\conda.exe）");
            out.put("envs", List.of());
            return out;
        }
        List<String> cmd = new ArrayList<>(condaCommand(root));
        cmd.addAll(List.of("env", "list", "--json"));
        Exec r = exec(cmd, 60, StandardCharsets.UTF_8, Map.of("PYTHONIOENCODING", "utf-8"));
        List<Map<String, Object>> envs = new ArrayList<>();
        try {
            JsonNode json = objectMapper.readTree(r.output.substring(Math.max(0, r.output.indexOf('{'))));
            JsonNode details = json.path("envs_details");
            for (JsonNode p : json.path("envs")) {
                Path envDir = Paths.get(p.asText());
                Path python = WINDOWS ? envDir.resolve("python.exe") : envDir.resolve("bin").resolve("python");
                boolean base = envDir.normalize().equals(root.normalize());
                String name = details.path(p.asText()).path("name").asText(base ? "base" : envDir.getFileName().toString());
                Map<String, Object> env = new LinkedHashMap<>();
                env.put("name", name);
                env.put("prefix", envDir.toString());
                env.put("pythonPath", python.toString());
                env.put("hasPython", Files.isRegularFile(python));
                env.put("base", base);
                envs.add(env);
            }
        } catch (IOException | RuntimeException e) {
            log.warn("解析 conda env list 输出失败：{}", e.getMessage());
            out.put("found", false);
            out.put("root", root.toString());
            out.put("message", "找到了 Conda（" + root + "），但执行 conda env list 失败：" + tail(r.output, 300));
            out.put("envs", List.of());
            return out;
        }
        out.put("found", true);
        out.put("root", root.toString());
        out.put("envs", envs);
        out.put("createCommand", "\"" + condaCommand(root).get(condaCommand(root).size() - 1)
                + "\" create -n nan_novel python=3.10 -y");
        return out;
    }

    private Path findCondaRoot() {
        String condaExe = System.getenv("CONDA_EXE");
        if (condaExe != null && !condaExe.isBlank()) {
            Path r = condaRootFrom(Paths.get(condaExe));
            if (r != null) {
                return r;
            }
        }
        Exec where = exec(WINDOWS ? List.of("where", "conda") : List.of("which", "conda"), 10, NATIVE, null);
        for (String line : where.output.split("\\R")) {
            if (!line.isBlank()) {
                Path r = condaRootFrom(Paths.get(line.trim()));
                if (r != null) {
                    return r;
                }
            }
        }
        String home = System.getProperty("user.home");
        List<Path> common = new ArrayList<>(List.of(
                Paths.get(home, "miniconda3"), Paths.get(home, "anaconda3"),
                Paths.get(home, "AppData", "Local", "miniconda3"), Paths.get(home, "AppData", "Local", "anaconda3")));
        if (WINDOWS) {
            common.add(Paths.get("C:\\ProgramData\\miniconda3"));
            common.add(Paths.get("C:\\ProgramData\\anaconda3"));
        } else {
            common.add(Paths.get("/opt/conda"));
        }
        return common.stream().map(this::condaRootFrom).filter(java.util.Objects::nonNull).findFirst().orElse(null);
    }

    /** 由安装目录 / conda.exe / conda.bat / _conda.exe 推出 Conda 安装根目录 */
    private Path condaRootFrom(Path p) {
        Path cur = Files.isDirectory(p) ? p : p.getParent();
        for (int i = 0; i < 3 && cur != null; i++, cur = cur.getParent()) {
            if (Files.isDirectory(cur.resolve("conda-meta"))
                    && (Files.isRegularFile(cur.resolve("Scripts").resolve("conda.exe"))
                    || Files.isRegularFile(cur.resolve("condabin").resolve("conda.bat"))
                    || Files.isRegularFile(cur.resolve("bin").resolve("conda")))) {
                return cur.toAbsolutePath().normalize();
            }
        }
        return null;
    }

    private List<String> condaCommand(Path root) {
        Path exe = root.resolve("Scripts").resolve("conda.exe");
        if (WINDOWS && Files.isRegularFile(exe)) {
            return List.of(exe.toString());
        }
        Path bat = root.resolve("condabin").resolve("conda.bat");
        if (WINDOWS && Files.isRegularFile(bat)) {
            return List.of("cmd", "/c", bat.toString());
        }
        return List.of(root.resolve("bin").resolve("conda").toString());
    }

    private Map<String, Object> minicondaGuide() {
        Map<String, Object> g = new LinkedHashMap<>();
        g.put("officialUrl", MINICONDA_OFFICIAL);
        g.put("officialDownload", "https://repo.anaconda.com/miniconda/Miniconda3-latest-Windows-x86_64.exe");
        g.put("tunaUrl", MINICONDA_TUNA);
        g.put("tunaDownload", MINICONDA_TUNA + "Miniconda3-latest-Windows-x86_64.exe");
        g.put("createCommand", "conda create -n nan_novel python=3.10 -y");
        g.put("installCommand", "conda activate nan_novel && pip install -r \"" + serviceDir().resolve("requirements.txt") + "\"");
        return g;
    }

    // ------------------------------------------------------------------ 浏览

    /** 「浏览」：列出目录下的子目录和 python 可执行文件（浏览器拿不到本地文件的完整路径，由后端代为浏览） */
    public Map<String, Object> browse(String path) {
        Map<String, Object> out = new LinkedHashMap<>();
        List<Map<String, Object>> entries = new ArrayList<>();
        if (path == null || path.isBlank()) {
            for (File r : File.listRoots()) {
                entries.add(Map.of("name", r.getPath(), "path", r.getPath(), "dir", true));
            }
            out.put("path", "");
            out.put("parent", null);
            out.put("entries", entries);
            return out;
        }
        Path dir = Paths.get(path.trim()).toAbsolutePath().normalize();
        if (!Files.isDirectory(dir)) {
            throw new BizException(400, "目录不存在：" + dir);
        }
        File[] children = dir.toFile().listFiles();
        if (children != null) {
            Arrays.stream(children)
                    .filter(f -> !f.isHidden() && (f.isDirectory() || PYTHON_EXE.matcher(f.getName()).matches()))
                    .sorted(Comparator.comparing((File f) -> !f.isDirectory()).thenComparing(f -> f.getName().toLowerCase(Locale.ROOT)))
                    .limit(1000)
                    .forEach(f -> entries.add(Map.of("name", f.getName(), "path", f.getAbsolutePath(), "dir", f.isDirectory())));
        }
        Path parent = dir.getParent();
        out.put("path", dir.toString());
        out.put("parent", parent == null ? "" : parent.toString());
        out.put("entries", entries);
        return out;
    }

    // ------------------------------------------------------------------ 检测

    /**
     * 真正执行一次所选 python.exe：校验版本、CUDA、依赖。level=ERROR 不保存；OK/WARN 保存为当前配置。
     */
    public Map<String, Object> check(String envType, String pythonPath, String condaRoot, String condaEnv) {
        String type = envType == null ? "" : envType.toUpperCase(Locale.ROOT);
        if (!List.of(PythonEnv.TYPE_SYSTEM, PythonEnv.TYPE_CONDA, PythonEnv.TYPE_VENV, PythonEnv.TYPE_CUSTOM).contains(type)) {
            throw new BizException(400, "环境类型无效：" + envType);
        }
        if (pythonPath == null || pythonPath.isBlank()) {
            throw new BizException(400, "请填写 python.exe 路径");
        }
        String python = pythonPath.trim().replaceAll("^\"|\"$", "");
        List<Map<String, Object>> problems = new ArrayList<>();
        Map<String, Object> result = new LinkedHashMap<>();
        result.put("envType", type);
        result.put("pythonPath", python);
        result.put("minVersion", minVersionText);
        result.put("problems", problems);
        result.put("checkedTime", LocalDateTime.now().toString());

        Path exe = Paths.get(python);
        if (Files.isDirectory(exe)) {
            Path inside = WINDOWS ? exe.resolve("python.exe") : exe.resolve("bin").resolve("python");
            Path scripts = exe.resolve("Scripts").resolve("python.exe");
            exe = Files.isRegularFile(inside) ? inside : scripts;
            result.put("pythonPath", exe.toString());
        }
        // 应用执行别名不是普通文件，先于「文件不存在」判断，给出更准确的提示
        if (isStoreStub(exe.toString())) {
            return fail(result, problems, "这是 Windows 应用商店的占位程序",
                    "WindowsApps\\python.exe 不是真正的 Python，运行会打开应用商店",
                    "请选择真实安装的 Python，或在「设置 → 应用 → 应用执行别名」中关闭 python.exe 别名");
        }
        if (!Files.isRegularFile(exe)) {
            return fail(result, problems, "路径无效", "文件不存在：" + exe, "请确认填写的是 python.exe 的完整路径（如 D:\\miniconda3\\envs\\xxx\\python.exe）");
        }

        JsonNode probe;
        try {
            probe = runProbe(exe.toString());
        } catch (ProbeException e) {
            return fail(result, problems, "无法运行该 Python", e.getMessage(), "确认路径正确、文件未损坏，并能在命令行中运行：\"" + exe + "\" --version");
        }
        result.put("python", objectMapper.convertValue(probe, Map.class));
        int[] ver = objectMapper.convertValue(probe.path("versionInfo"), int[].class);
        boolean versionOk = compareVersion(ver, minVersion) >= 0;
        result.put("versionOk", versionOk);
        String py = "\"" + exe + "\"";

        if (!versionOk) {
            problem(problems, "ERROR", "Python 版本过低：" + probe.path("version").asText(),
                    "本项目需要 Python >= " + minVersionText,
                    "conda create -n nan_novel python=3.10 -y   （或安装 Python 3.10+ 后重新选择）");
        }
        if ("32bit".equals(probe.path("arch").asText())) {
            problem(problems, "ERROR", "32 位 Python", "PyTorch 等依赖只提供 64 位版本", "请安装 64 位 Python 3.10+");
        }

        JsonNode reqs = probe.path("requirements");
        String[] labels = {"服务依赖（requirements.txt）", "本地模型依赖（requirements-local.txt）"};
        ArrayNode reqOut = objectMapper.createArrayNode();
        for (int i = 0; i < reqs.size(); i++) {
            ObjectNode r = ((ObjectNode) reqs.get(i)).put("label", i < labels.length ? labels[i] : reqs.get(i).path("file").asText());
            reqOut.add(r);
        }
        result.put("requirements", objectMapper.convertValue(reqOut, List.class));

        Path reqService = serviceDir().resolve("requirements.txt");
        Path reqLocal = serviceDir().resolve("requirements-local.txt");
        List<String> badService = badPackages(reqs.path(0));
        if (!badService.isEmpty()) {
            // AI 服务用这个 Python 启动，缺服务依赖就起不来，因此算未通过、不保存
            problem(problems, "ERROR", "服务依赖未满足：" + String.join("、", badService),
                    "缺少这些包时 AI 服务（文本提取 / 模型接口）无法启动",
                    py + " -m pip install -r \"" + reqService + "\"");
        }

        JsonNode cuda = probe.path("cuda");
        result.put("cuda", objectMapper.convertValue(cuda, Map.class));
        // torch 2.6 的 CUDA 安装包只支持 Python 3.9~3.13，更高版本建议新建 3.10 环境
        boolean torchWheel = ver.length >= 2 && ver[0] == 3 && ver[1] >= 9 && ver[1] <= 13;
        String torchCmd = torchWheel
                ? py + " -m pip install --no-cache-dir \"torch==2.6.0+cu124\" -f https://mirrors.aliyun.com/pytorch-wheels/cu124/"
                : "# Python " + probe.path("version").asText() + " 暂无 CUDA 版 torch 2.6 安装包，建议新建 3.10 环境：\n"
                  + "conda create -n nan_novel python=3.10 -y";
        if (!cuda.path("torchInstalled").asBoolean()) {
            problem(problems, "WARN", "未安装 PyTorch", "本地模型推理 / LoRA 微调不可用（文本提取等不受影响）",
                    torchCmd + "\n" + py + " -m pip install --no-cache-dir -r \"" + reqLocal + "\"");
        } else if (!cuda.path("cudaAvailable").asBoolean()) {
            String v = cuda.path("torchVersion").asText();
            String why = !cuda.path("error").isNull() ? "导入 torch 出错：" + cuda.path("error").asText()
                    : v.contains("+cpu") || cuda.path("cudaVersion").isNull() ? "安装的是 CPU 版 torch（" + v + "）"
                    : "torch " + v + " 无法使用 GPU，可能是 NVIDIA 驱动过旧或未安装";
            problem(problems, "WARN", "CUDA 不可用", why + "；本地训练需要 NVIDIA GPU",
                    py + " -m pip uninstall -y torch\n" + torchCmd);
        }
        List<String> badLocal = badPackages(reqs.path(1)).stream().filter(n -> !"torch".equalsIgnoreCase(n)).toList();
        if (!badLocal.isEmpty() && cuda.path("torchInstalled").asBoolean()) {
            problem(problems, "WARN", "本地模型依赖未满足：" + String.join("、", badLocal),
                    "本地推理 / 微调需要这些包", py + " -m pip install --no-cache-dir -r \"" + reqLocal + "\"");
        }

        String level = problems.stream().anyMatch(p -> "ERROR".equals(p.get("level"))) ? "ERROR"
                : problems.isEmpty() ? "OK" : "WARN";
        result.put("level", level);
        result.put("ok", !"ERROR".equals(level));
        if (!"ERROR".equals(level)) {
            save(type, exe.toString(), condaRoot, condaEnv, probe, level, result);
            result.put("saved", true);
            result.put("envFile", serviceDir().resolve(".python-env").toString());
        } else {
            result.put("saved", false);
        }
        return result;
    }

    private static List<String> badPackages(JsonNode reqFile) {
        List<String> bad = new ArrayList<>();
        for (JsonNode item : reqFile.path("items")) {
            if (!"ok".equals(item.path("status").asText())) {
                bad.add(item.path("name").asText());
            }
        }
        return bad;
    }

    private Map<String, Object> fail(Map<String, Object> result, List<Map<String, Object>> problems,
                                     String title, String detail, String fix) {
        problem(problems, "ERROR", title, detail, fix);
        result.put("level", "ERROR");
        result.put("ok", false);
        result.put("saved", false);
        return result;
    }

    private static void problem(List<Map<String, Object>> problems, String level, String title, String detail, String fix) {
        Map<String, Object> p = new LinkedHashMap<>();
        p.put("level", level);
        p.put("title", title);
        p.put("detail", detail);
        p.put("fix", fix);
        problems.add(p);
    }

    private static int compareVersion(int[] a, int[] b) {
        for (int i = 0; i < Math.max(a.length, b.length); i++) {
            int x = i < a.length ? a[i] : 0;
            int y = i < b.length ? b[i] : 0;
            if (x != y) {
                return Integer.compare(x, y);
            }
        }
        return 0;
    }

    private JsonNode runProbe(String python) throws ProbeException {
        Path script = null;
        try (InputStream in = new ClassPathResource("python/env_probe.py").getInputStream()) {
            script = Files.createTempFile("nan_novel_env_probe_", ".py");
            Files.write(script, in.readAllBytes());
            List<String> cmd = List.of(python, "-I", script.toString(),
                    serviceDir().resolve("requirements.txt").toString(),
                    serviceDir().resolve("requirements-local.txt").toString());
            // 导入 torch 并初始化 CUDA 可能要几十秒
            Exec r = exec(cmd, 150, StandardCharsets.UTF_8, Map.of("PYTHONIOENCODING", "utf-8"));
            if (r.timedOut) {
                throw new ProbeException("检测超时（150 秒），该 Python 可能卡在导入 torch 上");
            }
            int at = r.output.lastIndexOf(PROBE_MARK);
            if (at < 0) {
                throw new ProbeException("执行失败（退出码 " + r.exitCode + "）：" + tail(r.output, 500));
            }
            String json = r.output.substring(at + PROBE_MARK.length()).lines().findFirst().orElse("");
            return objectMapper.readTree(json);
        } catch (IOException e) {
            throw new ProbeException("无法执行：" + e.getMessage());
        } finally {
            if (script != null) {
                try {
                    Files.deleteIfExists(script);
                } catch (IOException ignored) {
                    // 临时文件，删除失败不影响结果
                }
            }
        }
    }

    // ------------------------------------------------------------------ 保存 / 当前配置

    private void save(String type, String python, String condaRoot, String condaEnv, JsonNode probe,
                        String level, Map<String, Object> result) {
        LocalDateTime now = LocalDateTime.now();
        mapper.update(null, new LambdaUpdateWrapper<PythonEnv>().set(PythonEnv::getActive, false));
        mapper.delete(new LambdaQueryWrapper<PythonEnv>().eq(PythonEnv::getPythonPath, python));
        PythonEnv env = new PythonEnv();
        env.setEnvType(type);
        env.setPythonPath(python);
        env.setCondaRoot(PythonEnv.TYPE_CONDA.equals(type) ? condaRoot : null);
        env.setCondaEnv(PythonEnv.TYPE_CONDA.equals(type) ? condaEnv : probe.path("condaEnv").asText(null));
        env.setPythonVersion(probe.path("version").asText());
        env.setCudaAvailable(probe.path("cuda").path("cudaAvailable").asBoolean());
        env.setGpuName(probe.path("cuda").path("gpuName").asText(null));
        env.setTorchVersion(probe.path("cuda").path("torchVersion").asText(null));
        env.setStatus(level);
        env.setActive(true);
        env.setCheckedTime(now);
        env.setCreateTime(now);
        try {
            env.setCheckResult(objectMapper.writeValueAsString(result));
        } catch (IOException e) {
            env.setCheckResult(null);
        }
        mapper.insert(env);
        writeEnvFile(python);
    }

    /** start.bat 用 `set /p PYEXE=<python-service\.python-env` 读取，cmd 以控制台代码页（中文系统 GBK）解析 */
    private void writeEnvFile(String python) {
        Path file = serviceDir().resolve(".python-env");
        try {
            if (Files.isDirectory(serviceDir())) {
                Files.writeString(file, python + System.lineSeparator(), WINDOWS ? NATIVE : StandardCharsets.UTF_8);
            }
        } catch (IOException e) {
            log.warn("写入 {} 失败：{}", file, e.getMessage());
        }
    }

    private PythonEnv findActive() {
        return mapper.selectOne(new LambdaQueryWrapper<PythonEnv>().eq(PythonEnv::getActive, true).last("LIMIT 1"));
    }

    /** 当前生效的配置（含上次完整检测结果）；文件已被删除时 exists=false */
    public Map<String, Object> current() {
        PythonEnv env = findActive();
        if (env == null) {
            return null;
        }
        Map<String, Object> out = objectMapper.convertValue(env, Map.class);
        out.remove("checkResult");
        out.put("exists", Files.isRegularFile(Paths.get(env.getPythonPath())));
        try {
            out.put("lastResult", env.getCheckResult() == null ? null : objectMapper.readValue(env.getCheckResult(), Map.class));
        } catch (IOException e) {
            out.put("lastResult", null);
        }
        return out;
    }

    // ------------------------------------------------------------------ 进程

    private record Exec(int exitCode, String output, boolean timedOut) {
    }

    private static class ProbeException extends Exception {
        ProbeException(String message) {
            super(message);
        }
    }

    /** 执行外部命令（stdout+stderr 合并），超时则强制结束 */
    private static Exec exec(List<String> cmd, int timeoutSeconds, Charset charset, Map<String, String> env) {
        ProcessBuilder pb = new ProcessBuilder(cmd).redirectErrorStream(true);
        if (env != null) {
            pb.environment().putAll(env);
        }
        try {
            Process p = pb.start();
            p.getOutputStream().close();
            ByteArrayOutputStream buf = new ByteArrayOutputStream();
            Thread reader = new Thread(() -> {
                try (InputStream in = p.getInputStream()) {
                    in.transferTo(buf);
                } catch (IOException ignored) {
                    // 进程被结束时流会关闭
                }
            });
            reader.setDaemon(true);
            reader.start();
            boolean done = p.waitFor(timeoutSeconds, TimeUnit.SECONDS);
            if (!done) {
                p.descendants().forEach(ProcessHandle::destroyForcibly);
                p.destroyForcibly();
            }
            reader.join(2000);
            return new Exec(done ? p.exitValue() : -1, buf.toString(charset), !done);
        } catch (IOException e) {
            return new Exec(-1, e.getMessage() == null ? "" : e.getMessage(), false);
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
            return new Exec(-1, "interrupted", false);
        }
    }

    private static String tail(String s, int max) {
        String t = s == null ? "" : s.strip();
        return t.length() > max ? "…" + t.substring(t.length() - max) : t;
    }
}
