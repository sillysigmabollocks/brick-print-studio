export function setNumber(value) {
  const cleaned = value.trim();
  if (/^\d{3,10}(?:-\d{1,4})?$/.test(cleaned)) return cleaned;

  let url;
  try {
    url = new URL(cleaned.includes('://') ? cleaned : 'https://' + cleaned);
  } catch {
    throw new Error('Enter a set number such as 75394-1 or a supported set link.');
  }
  if (url.protocol !== 'https:' || url.username || url.password) {
    throw new Error('Use a public HTTPS set link.');
  }

  const host = url.hostname.toLowerCase().replace(/^www\./, '');
  let match;
  if (host === 'lego.com') {
    match = url.pathname.match(/\/(?:product\/[^/]*-|buildinginstructions\/)(\d{3,10})\/?$/i);
  } else if (host === 'bricklink.com') {
    match = (url.searchParams.get('S') ?? url.searchParams.get('s') ?? '').match(/^(\d{3,10}(?:-\d{1,4})?)$/);
  } else if (host === 'rebrickable.com' || host === 'brickset.com') {
    match = url.pathname.match(/^\/sets?\/(\d{3,10}(?:-\d{1,4})?)(?:\/|$)/i);
  }
  if (!match) {
    throw new Error('Enter a set number or a set page from LEGO, BrickLink, Rebrickable, or Brickset.');
  }
  return match[1];
}
