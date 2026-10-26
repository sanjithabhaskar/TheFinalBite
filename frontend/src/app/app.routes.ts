import { Routes } from '@angular/router';
import { GroupLobby } from './group-lobby/group-lobby';
import { Home } from './home/home';
import { Join } from './join/join';
import { Matches } from './matches/matches';
import { RestaurantList } from './restaurant-list/restaurant-list';
import { Swipe } from './swipe/swipe';

export const routes: Routes = [
  { path: '', component: Home },
  { path: 'join/:code', component: Join },
  { path: 'group/:code', component: GroupLobby },
  { path: 'swipe/:code', component: Swipe },
  { path: 'matches/:code', component: Matches },
  { path: 'restaurants', component: RestaurantList },
];