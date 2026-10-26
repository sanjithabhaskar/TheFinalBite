// These mirror the JSON your Django API returns.
export interface Restaurant {
  id: number;
  name: string;
  neighborhood: string | null;
  cuisines: string[] | null;
  rating: number | null;
  median_entree_price: number | null;   // null for tasting-menu places
  min_entree_price: number | null;
  max_entree_price: number | null;
  dietary_tags: string[] | null;
  menu_style: string | null;
}

export interface Member {
  id: number;
  name: string;
  max_entree_budget: number;
  dietary_restrictions: string[];
  cuisine_prefs: string[];
}

export interface Group {
  id: number;
  invite_code: string;
  name: string;
  host_member_id: number | null;
  started: boolean;
  members: Member[];
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
export const DIETARY_OPTIONS = ['vegetarian', 'vegan', 'gluten_free', 'dairy_free', 'nut_free', 'halal', 'kosher'];
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