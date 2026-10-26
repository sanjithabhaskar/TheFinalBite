// These mirror the JSON your Django API returns.
export interface Restaurant {
  id: number;
  name: string;
  neighborhood: string | null;
  address: string | null;
  cuisines: string[] | null;
  rating: number | null;
  median_entree_price: number | null;   // null for tasting-menu places
  min_entree_price: number | null;
  max_entree_price: number | null;
  dietary_tags: string[] | null;
  menu_style: string | null;
  website: string | null;
  menu_url: string | null;
  image_url: string | null;
}

export interface Member {
  id: number;
  name: string;
  max_entree_budget: number;
  dietary_restrictions: string[];
  cuisine_prefs: string[];
}

/** What the group may see about a person: a name and how far through the deck they are. */
export interface PublicMember {
  id: number;
  name: string;
  swiped: number;
}

export interface Group {
  id: number;
  invite_code: string;
  name: string;
  host_member_id: number | null;
  host_name: string | null;
  started: boolean;
  deck_size: number;
  members: PublicMember[];
}

/** Returned once when you join: includes your private token. */
export interface JoinedMember extends Member {
  token: string;
}

export interface NextCardsResponse {
  done: number;
  total: number;
  cards: Restaurant[];
}

export interface MatchesResponse {
  member_count: number;
  matches: Restaurant[];
}

export interface NewMember {
  name: string;
  max_entree_budget: number;
  dietary_restrictions: string[];
  cuisine_prefs: string[];
}

// Pick-lists for the join form. Values must match what the API / database use.
export const DIETARY_OPTIONS = ['vegan', 'vegetarian', 'gluten_free', 'dairy_free', 'nut_free', 'halal', 'kosher'];
export const CUISINE_OPTIONS = [
  'american', 'brunch', 'burger', 'chinese', 'french', 'greek', 'indian', 'italian', 'japanese',
  'korean', 'mediterranean', 'mexican', 'middle_eastern', 'pizza', 'ramen', 'seafood',
  'steak_house', 'sushi', 'thai', 'vegan', 'vietnamese',
];

/** 'gluten_free' -> 'Gluten free' */
export function pretty(value: string): string {
  const s = value.replace(/_/g, ' ');
  return s.charAt(0).toUpperCase() + s.slice(1);
}

/** A soft gradient per cuisine, used until we have real restaurant photos. */
const CUISINE_COLORS: Record<string, [string, string]> = {
  italian: ['#f4a259', '#bc4b51'], pizza: ['#f4a259', '#bc4b51'], japanese: ['#8ecae6', '#355070'],
  sushi: ['#8ecae6', '#355070'], ramen: ['#ffb703', '#d62828'], chinese: ['#e63946', '#8d0801'],
  korean: ['#ff7b54', '#a4133c'], thai: ['#80b918', '#2b9348'], vietnamese: ['#80b918', '#2b9348'],
  indian: ['#f9a03f', '#9d0208'], mexican: ['#f77f00', '#6a994e'], french: ['#cdb4db', '#5e548e'],
  mediterranean: ['#48cae4', '#0077b6'], greek: ['#48cae4', '#0077b6'], american: ['#e07a5f', '#3d405b'],
  burger: ['#e07a5f', '#3d405b'], seafood: ['#90e0ef', '#023e8a'], brunch: ['#ffd166', '#ef476f'],
};
export function cuisineGradient(cuisines: string[] | null): string {
  const key = (cuisines ?? []).find((c) => CUISINE_COLORS[c]);
  const [a, b] = key ? CUISINE_COLORS[key] : ['#d9b38c', '#7a5c58'];
  return `linear-gradient(135deg, ${a}, ${b})`;
}

export function initials(name: string): string {
  const parts = name.trim().split(/\s+/).filter(Boolean);
  if (parts.length === 0) return '?';
  // one word -> first two letters ("Sanji" -> "SA"); several -> first letters of the first two
  const letters = parts.length === 1 ? parts[0].slice(0, 2) : parts[0][0] + parts[1][0];
  return letters.toUpperCase();
}