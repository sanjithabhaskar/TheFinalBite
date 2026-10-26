import { Component, inject, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { catchError, EMPTY, switchMap, timer } from 'rxjs';
import { MatchesResponse, pretty } from '../models';
import { RestaurantApi } from '../services/restaurant-api';

@Component({
  imports: [RouterLink],
  selector: 'app-matches',
  styleUrl: './matches.css',
  templateUrl: './matches.html',
})
export class Matches {
  private api = inject(RestaurantApi);

  code = (inject(ActivatedRoute).snapshot.paramMap.get('code') ?? '').toUpperCase();
  data = signal<MatchesResponse | null>(null);
  error = signal('');
  pretty = pretty;

  constructor() {
    // Refresh every 5 seconds so new matches appear as other people swipe.
    timer(0, 5000)
      .pipe(
        switchMap(() =>
          this.api.getMatches(this.code).pipe(
            catchError(() => {
              this.error.set("Couldn't load matches.");
              return EMPTY;
            }),
          ),
        ),
        takeUntilDestroyed(),
      )
      .subscribe((d) => {
        this.error.set('');
        this.data.set(d);
      });
  }
}
