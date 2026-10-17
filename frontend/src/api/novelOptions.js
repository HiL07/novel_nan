import mock from '@/mock/novelOptionSchema'

/**
 * 小说创作选项数据源。
 * 目前返回本地示例数据（src/mock/novelOptionSchema.js）；接入数据库后，在这里改为调用后端接口，
 * 例如 request.get('/api/novel/options/schema').then((res) => res.data)，返回同样结构即可，页面无需改动。
 */

const copy = (v) => JSON.parse(JSON.stringify(v))

/**
 * 选项结构
 * @returns {Promise<{code:number,message:string,data:{categories:object[],elementTemplates:object[],genericSuggestions:object[]}}>}
 */
export function getOptionSchema() {
  return Promise.resolve({ code: 0, message: 'ok', data: copy(mock) })
}
