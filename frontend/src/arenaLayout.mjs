/**
 * Generates a SCHEMATIC (not-to-scale) venue overview from actual API section groups.
 * There is exactly one interactive area per real section: no imaginary inventory.
 */
const palette = ['#FFD58C', '#F67C97', '#DC5F9C', '#B678CD', '#7BA7CF', '#66C4B0', '#F0A569', '#A794DD'];
const radians = degrees => degrees * Math.PI / 180;
function point(cx, cy, rx, ry, degrees) {
  const theta = radians(degrees);
  return [cx + rx * Math.cos(theta), cy + ry * Math.sin(theta)];
}
function ringPath(cx, cy, outer, inner, from, to) {
  const count = Math.max(14, Math.ceil(Math.abs(to - from) / 5));
  const outerPoints = Array.from({ length: count + 1 }, (_, i) => point(cx, cy, outer[0], outer[1], from + (to - from) * i / count));
  const innerPoints = Array.from({ length: count + 1 }, (_, i) => point(cx, cy, inner[0], inner[1], to + (from - to) * i / count));
  return [...outerPoints, ...innerPoints].map(([x,y],i) => `${i === 0 ? 'M':'L'}${x.toFixed(1)} ${y.toFixed(1)}`).join(' ') + ' Z';
}

export function buildArenaPieces(zones) {
  if (!Array.isArray(zones) || zones.length === 0) return [];
  const cx = 440, cy = 164;
  if (zones.length <= 2) {
    return zones.map((zone, i) => {
      const outer = i === 0 ? [236, 187] : [326, 256];
      const inner = i === 0 ? [165, 124] : [255, 196];
      const middleX = (outer[0] + inner[0]) / 2;
      const middleY = (outer[1] + inner[1]) / 2;
      const [labelX,labelY] = point(cx, cy, middleX, middleY, 90);
      return { section: zone.section, path: ringPath(cx, cy, outer, inner, -14, 194), labelX, labelY, color: palette[i%palette.length] };
    });
  }
  // More sections are arranged in one or two labelled tiers as needed.
  // This is a visual map, NOT an assertion about the venue's true geometry.
  const tierCount = zones.length > 8 ? 2 : 1;
  const split = Math.ceil(zones.length / tierCount);
  return zones.map((zone, i) => {
    const tier = Math.floor(i / split);
    const withinTier = i - tier * split;
    const sectionsInTier = Math.min(split, zones.length - tier * split);
    const start = -15 + withinTier * 210 / sectionsInTier + 1.6;
    const end = -15 + (withinTier + 1) * 210 / sectionsInTier - 1.6;
    const outer = tier === 0 ? [250, 195] : [330, 265];
    const inner = tier === 0 ? [178, 129] : [263, 207];
    const mid = (start + end) / 2;
    const [labelX, labelY] = point(cx, cy, (outer[0]+inner[0])/2, (outer[1]+inner[1])/2, mid);
    return { section: zone.section, path: ringPath(cx, cy, outer, inner, start, end), labelX, labelY, color: palette[i%palette.length] };
  });
}

export function sectionAvailable(zone) {
  return zone?.rows?.reduce((sum, row) => sum + row.slots.filter(seat => seat && seat.status === 'AVAILABLE').length, 0) ?? 0;
}
