import { inject, Service } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';
import { Group, MatchesResponse, Member, NewMember, Restaurant } from '../models';

@Service()
export class RestaurantApi {
  private http = inject(HttpClient);
  private base = 'http://127.0.0.1:8000/api';

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

  joinGroup(code: string, member: NewMember): Observable<Member> {
    return this.http.post<Member>(`${this.base}/groups/${code}/join/`, member);
  }

  startGroup(code: string, memberId: number): Observable<Group> {
    return this.http.post<Group>(`${this.base}/groups/${code}/start/`, { member_id: memberId });
  }

  getNextCards(memberId: number): Observable<Restaurant[]> {
    return this.http.get<Restaurant[]>(`${this.base}/members/${memberId}/next/`);
  }

  swipe(memberId: number, restaurantId: number, liked: boolean): Observable<unknown> {
    return this.http.post(`${this.base}/swipes/`, {
      member_id: memberId,
      restaurant_id: restaurantId,
      liked,
    });
  }

  getMatches(code: string): Observable<MatchesResponse> {
    return this.http.get<MatchesResponse>(`${this.base}/groups/${code}/matches/`);
  }
}