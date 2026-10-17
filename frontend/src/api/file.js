import axios from 'axios'

// 后端地址（见 docx/fronted_vue3/api/file_upload.md）
const baseURL = 'http://localhost:8080'

const request = axios.create({
  baseURL,
  timeout: 60000
})

/**
 * 上传文件
 * POST /api/file/upload，multipart/form-data，表单字段名固定为 file
 * @param {File} file 待上传文件
 * @returns {Promise<{code:number,message:string,data:object}>}
 */
export function uploadFile(file) {
  const fd = new FormData()
  fd.append('file', file)
  return request
    .post('/api/file/upload', fd, {
      headers: { 'Content-Type': 'multipart/form-data' }
    })
    .then((res) => res.data)
}

/**
 * 批量上传：前端循环调单接口，每个文件独立成功/失败，互不影响
 * @param {File[]} files 待上传文件列表
 * @returns {Promise<Array<{file: File, status: 'ok'|'fail', info?: object, message?: string}>>}
 */
export function uploadFiles(files) {
  return Promise.allSettled(files.map((f) => uploadFile(f))).then((settled) =>
    settled.map((result, i) => {
      const file = files[i]
      if (result.status === 'fulfilled' && result.value?.code === 0) {
        return { file, status: 'ok', info: result.value.data }
      }
      const message =
        result.status === 'rejected'
          ? result.reason?.response?.data?.message || result.reason?.message || '上传失败'
          : result.value?.message || '上传失败'
      return { file, status: 'fail', message }
    })
  )
}

/**
 * 文件列表（按上传时间倒序）
 * GET /api/file/list
 * @returns {Promise<{code:number,message:string,data:object[]}>}
 */
export function listFiles() {
  return request.get('/api/file/list').then((res) => res.data)
}

/** 预览地址：可直接作为 <img> / <iframe> 的 src */
export function previewUrl(id) {
  return `${baseURL}/api/file/preview/${id}`
}

/** 下载地址 */
export function downloadUrl(id) {
  return `${baseURL}/api/file/download/${id}`
}

/** 触发浏览器下载（后端已设 Content-Disposition: attachment） */
export function downloadFile(id) {
  const a = document.createElement('a')
  a.href = downloadUrl(id)
  a.style.display = 'none'
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
}

/** 读取文本内容（纯文本预览，见 view/file_manage.md） */
export function fetchText(id) {
  return request.get(`/api/file/preview/${id}`, { responseType: 'text' }).then((res) => res.data)
}

/**
 * 文件类型分类：ext → 分类（见 docx/fronted_vue3/api/file_manage.md）
 * @returns {'text'|'office'|'image'|'binary'|'other'}
 */
export function classify(ext) {
  const e = (ext || '').toLowerCase()
  if (['txt', 'md', 'js', 'py', 'json', 'sql', 'html', 'vue'].includes(e)) return 'text'
  if (['docx', 'pdf'].includes(e)) return 'office'
  if (['png', 'jpg', 'jpeg', 'webp'].includes(e)) return 'image'
  if (['zip', 'exe', 'bin'].includes(e)) return 'binary'
  return 'other'
}
