import type {CSSProperties} from 'react';
const paths:Record<string,string>={
  send:'M12 19V5m-6 6 6-6 6 6',plus:'M12 5v14M5 12h14',close:'m6 6 12 12M6 18 18 6',
  chevron:'m6 9 6 6 6-6',menu:'M4 6h16M4 12h16M4 18h16',more:'M5 12h.01M12 12h.01M19 12h.01',
  settings:'M4 6h8m4 0h4M4 12h2m4 0h10M4 18h12m4 0h0M12 3v6M6 9v6M16 15v6',
  attach:'m8 13 7-7a3 3 0 0 1 4 4l-9 9a5 5 0 0 1-7-7l10-10',
  share:'M8 10 16 6M8 14l8 4M20 5a3 3 0 1 1-6 0 3 3 0 0 1 6 0ZM9 12a3 3 0 1 1-6 0 3 3 0 0 1 6 0Zm11 7a3 3 0 1 1-6 0 3 3 0 0 1 6 0Z',
  download:'M12 3v12m-5-5 5 5 5-5M5 16v4h14v-4',stop:'M7 7h10v10H7z',file:'M6 3h8l4 4v14H6zM14 3v5h4',check:'m5 12 4 4L19 6',
};
export function Icon({name,style}:{name:string;style?:CSSProperties}){return <svg className="icon" style={style} width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d={paths[name]??paths.more}/></svg>}
