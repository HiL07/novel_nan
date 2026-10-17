import request from './request'

/** Python 环境选择与检测（Java 后端执行所选 python.exe）。均返回 {code, message, data} */

/** PATH 上的 python、Conda 环境、项目 venv 默认路径、当前配置、Miniconda 指引；GET /api/python-env/discover */
export const discoverEnvs = () => request.get('/api/python-env/discover', { timeout: 90000 }).then((res) => res.data)

/** 列出 Conda 环境；condaPath 为 Conda 安装目录或 conda.exe，留空自动查找；GET /api/python-env/conda/envs */
export const listCondaEnvs = (condaPath) =>
  request.get('/api/python-env/conda/envs', { params: { condaPath }, timeout: 90000 }).then((res) => res.data)

/** 浏览目录（子目录 + python 可执行文件），path 为空返回盘符；GET /api/python-env/browse */
export const browseDir = (path) => request.get('/api/python-env/browse', { params: { path } }).then((res) => res.data)

/**
 * 执行检测；通过（OK/WARN）后端自动保存为当前配置。导入 torch 可能较慢，超时放宽到 3 分钟
 * POST /api/python-env/check {envType: SYSTEM|CONDA|VENV|CUSTOM, pythonPath, condaRoot?, condaEnv?}
 */
export const checkEnv = (body) => request.post('/api/python-env/check', body, { timeout: 180000 }).then((res) => res.data)

/** 当前生效配置（无则 data 为 null）；GET /api/python-env/current */
export const currentEnv = () => request.get('/api/python-env/current').then((res) => res.data)
