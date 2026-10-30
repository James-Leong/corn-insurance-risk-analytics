<script setup lang="ts">
withDefaults(defineProps<{ name: string; size?: number }>(), { size: 20 })
const paths: Record<string, string> = {
  grain:'M12 21V4M12 9C7 9 5 6 5 3c4 0 7 2 7 6Zm0 5c-5 0-7-3-7-6 4 0 7 2 7 6Zm0-5c5 0 7-3 7-6-4 0-7 2-7 6Zm0 5c5 0 7-3 7-6-4 0-7 2-7 6Z',
  policy:'M7 3h10l3 4v14H4V3h3Zm9 0v5h4M8 12h8M8 16h5',
  research:'M4 20V11m5 9V4m6 16v-6m5 6V7M3 20h19',
  risk:'M12 3 3 7v5c0 5 9 9 9 9s9-4 9-9V7l-9-4ZM8 12l3 3 5-6',
  settlement:'M3 7h18v13H3V7Zm2-4h14v4M7 12h3m4 0h3M7 16h3m4 0h3',
  arrow:'M5 12h14m-5-5 5 5-5 5', chevron:'m9 5 7 7-7 7',down:'m6 9 6 6 6-6',plus:'M12 5v14M5 12h14',close:'m6 6 12 12M6 18 18 6',search:'M21 21l-5-5m2-6a8 8 0 1 1-16 0 8 8 0 0 1 16 0Z',download:'M12 3v12m-5-5 5 5 5-5M4 16v5h16v-5',upload:'M12 16V4m-5 5 5-5 5 5M4 16v5h16v-5',refresh:'M20 7a9 9 0 1 0 1 8M20 2v6h-6',bell:'M18 8a6 6 0 0 0-12 0c0 7-3 7-3 9h18c0-2-3-2-3-9M9 21h6',logout:'M9 4H4v16h5m5-16 7 8-7 8m-5-8h12',check:'m5 12 4 4L19 6',clock:'M12 7v6l4 2M22 12a10 10 0 1 1-20 0 10 10 0 0 1 20 0Z',info:'M12 11v6m0-10v1M22 12a10 10 0 1 1-20 0 10 10 0 0 1 20 0Z',file:'M14 2H4v20h16V8l-6-6Zm0 0v6h6M8 13h8m-8 4h5',filter:'M3 5h18M6 12h12m-9 7h6',link:'m10 13 4-4M8 16l-1 1a4 4 0 0 1-6-6l5-5a4 4 0 0 1 6 0m4 2 1-1a4 4 0 0 1 6 6l-5 5a4 4 0 0 1-6 0',calendar:'M4 5h16v16H4V5Zm3-3v6m10-6v6M4 10h16',building:'M4 21V7l8-4 8 4v14M8 8h1m6 0h1m-8 4h1m6 0h1m-8 4h1m6 0h1m-5 5v-4h2v4',menu:'M4 6h16M4 12h16M4 18h16',warning:'m12 3 10 18H2L12 3Zm0 6v5m0 3v1',eye:'M2 12s4-7 10-7 10 7 10 7-4 7-10 7S2 12 2 12Zm13 0a3 3 0 1 1-6 0 3 3 0 0 1 6 0Z',external:'M14 3h7v7m0-7L10 14M10 3H3v18h18v-7',user:'M16 7a4 4 0 1 1-8 0 4 4 0 0 1 8 0ZM4 21v-3a8 8 0 0 1 16 0v3',spark:'m12 3 2.5 6.5L21 12l-6.5 2.5L12 21l-2.5-6.5L3 12l6.5-2.5L12 3Z'
}
</script>
<template><svg :width="size" :height="size" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.65" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path :d="paths[name] || paths.file" /></svg></template>
