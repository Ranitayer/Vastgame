<script lang="ts">
  let { kind }: { kind: 'cpu' | 'memory' | 'download' | 'upload' } = $props();
  const paths = {
    cpu: 'M6 6h12v12H6z M9 9h6v6H9z M9 3v3m6-3v3M9 18v3m6-3v3M3 9h3m-3 6h3m12-6h3m-3 6h3',
    memory: 'M3 7h18v10H3z M7 10v4m5-4v4m5-4v4 M6 17v3m4-3v3m4-3v3m4-3v3',
    download: 'M12 3v12m-5-5 5 5 5-5 M4 17v4h16v-4',
    upload: 'M12 15V3m-5 5 5-5 5 5 M4 17v4h16v-4',
  };
</script>
<svg viewBox="0 0 24 24" aria-hidden="true"><path d={paths[kind]}/></svg>
