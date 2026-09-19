import {
  createRouter,
  createMemoryHistory,
  createWebHistory,
  type RouterHistory,
} from 'vue-router'

export function createAppRouter(history: RouterHistory = createWebHistory()) {
  const routePlaceholder = { render: () => null }
  return createRouter({
    history,
    routes: [
      { path: '/', name: 'home', component: routePlaceholder },
      {
        path: '/study/:spaceId/card/:cardId',
        name: 'study',
        component: routePlaceholder,
        props: true,
      },
      { path: '/:pathMatch(.*)*', redirect: '/' },
    ],
  })
}

export const router = createAppRouter(
  typeof window === 'undefined' ? createMemoryHistory() : createWebHistory(),
)
