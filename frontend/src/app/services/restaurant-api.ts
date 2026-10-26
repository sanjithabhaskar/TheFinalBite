import { inject, Service } from '@angular/core';
import { HttpClient, HttpHeaders } from '@angular/common/http';
import { Observable } from 'rxjs';
import {
  Group, JoinedMember, MatchesResponse, Member, NewMember, NextCardsResponse, Restaurant,
} from '../models';
import { Me } from './session';

@Service()
export class RestaurantApi {
  private http = inject(HttpClient);
  private base = 'https://thefinalbite.onrender.com/api';
  

  private auth(me: Me) {
    return { headers: new HttpHeaders({ 'X-Member-Token': me.token }) };
  }

  getRestaurants(maxPrice?: number): Observable<Restaurant[]> {
    const query = maxPrice ? `?max_price=${maxPrice}` : '';
    return this.http.get<Restaurant[]>(`${this.base}/restaurants/${query}`);
  }

  createGroup(name: string): Observable<Group> {
    return this.http.post<Group>(`${this.base}/groups/`, { name });
  }

  getGroup(code: string): Observable<Group> {
    return this.http.get<Group>(`${this.base}/groups/${code}/`);
  }

  joinGroup(code: string, member: NewMember): Observable<JoinedMember> {
    return this.http.post<JoinedMember>(`${this.base}/groups/${code}/join/`, member);
  }

  /** Your own preferences (nobody else can read these). */
  getMe(me: Me): Observable<Member> {
    return this.http.get<Member>(`${this.base}/members/${me.id}/`, this.auth(me));
  }

  updateMe(me: Me, changes: Partial<NewMember>): Observable<Member> {
    return this.http.patch<Member>(`${this.base}/members/${me.id}/`, changes, this.auth(me));
  }

  startGroup(code: string, me: Me): Observable<Group> {
    return this.http.post<Group>(`${this.base}/groups/${code}/start/`, { member_id: me.id }, this.auth(me));
  }

  getNextCards(me: Me): Observable<NextCardsResponse> {
    return this.http.get<NextCardsResponse>(`${this.base}/members/${me.id}/next/`, this.auth(me));
  }

  swipe(me: Me, restaurantId: number, liked: boolean): Observable<unknown> {
    return this.http.post(
      `${this.base}/swipes/`,
      { member_id: me.id, restaurant_id: restaurantId, liked },
      this.auth(me),
    );
  }

  getMatches(code: string): Observable<MatchesResponse> {
    return this.http.get<MatchesResponse>(`${this.base}/groups/${code}/matches/`);
  }
}