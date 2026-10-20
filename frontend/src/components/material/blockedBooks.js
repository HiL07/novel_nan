import { ref, watch } from 'vue'

/**
 * 工作区里「屏蔽的来源书」：AI 构思 / AI 填写设定 / 选素材时不使用这些书的素材（保留的素材除外）。
 * 按工作区记在本机浏览器（同一工作区的各面板共用一份）；后端每次请求按 excludeBooks 过滤。
 */
const cache = new Map()

export function useBlockedBooks(novelId) {
  const key = `nan_novel.blockedBooks.${novelId || 'global'}`
  if (cache.has(key)) return cache.get(key)
  let initial = []
  try {
    initial = JSON.parse(localStorage.getItem(key) || '[]')
  } catch {
    initial = []
  }
  const books = ref(Array.isArray(initial) ? initial : [])
  watch(books, (v) => {
    try {
      localStorage.setItem(key, JSON.stringify(v))
    } catch {
      // 存储不可用：本次会话内仍然有效
    }
  }, { deep: true })
  cache.set(key, books)
  return books
}
