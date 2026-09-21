export interface AffiliationStyle { label: string; color: string }
export interface AffiliationConfig {
  styles: Record<string, AffiliationStyle>;
  aliases: Record<string, string>;
  entityDefaults: Record<string, string>;
  outlinePixels: number;
  selectedOutlinePixels: number;
}
export interface Appearance extends AffiliationStyle { key: string; reported: string; source: 'backend' | 'display-config' | 'unknown' | 'unmapped' }
const normalize = (value: string) => value.trim().toLowerCase().replace(/\s+/g, ' ');
const own = (value: object, key: string) => Object.prototype.hasOwnProperty.call(value, key);
export function validateAffiliations(config: AffiliationConfig): void {
  if (!config?.styles?.unknown || !config.aliases || !config.entityDefaults) throw new Error('缺少阵营显示配置');
  for (const style of Object.values(config.styles)) if (!style.label || !/^#[0-9a-f]{6}$/i.test(style.color)) throw new Error('阵营颜色配置无效');
  for (const key of [...Object.values(config.aliases), ...Object.values(config.entityDefaults)]) if (!own(config.styles,key)) throw new Error('阵营映射未定义');
  for (const size of [config.outlinePixels,config.selectedOutlinePixels]) if (!Number.isFinite(size) || size < 0.5 || size > 4) throw new Error('描边宽度无效');
}
export function appearance(id: string, entity: Record<string, unknown>, config: AffiliationConfig): Appearance {
  const configuration=entity.configuration as Record<string, unknown> | undefined;
  const reported=typeof configuration?.Affiliation==='string'?configuration.Affiliation.trim():'';
  const name=normalize(reported),mapped=own(config.aliases,name)?config.aliases[name]:own(config.styles,name)?name:undefined;
  // Explicit backend affiliation takes priority. User defaults only fill Unknown/missing.
  if (mapped && mapped!=='unknown') return {...config.styles[mapped],key:mapped,reported,source:'backend'};
  if (name && mapped!=='unknown') return {...config.styles.unknown,key:'unknown',label:'未配置：'+reported.slice(0,48),reported,source:'unmapped'};
  const fallback=own(config.entityDefaults,id)?config.entityDefaults[id]:'unknown';
  return {...config.styles[fallback],key:fallback,reported,source:fallback==='unknown'?'unknown':'display-config'};
}
