import { Component, computed, inject, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { ActivatedRoute, Router, RouterLink } from '@angular/router';
import { catchError, EMPTY, forkJoin, switchMap, timer } from 'rxjs';
import { cuisineGradient, Group, initials, pretty, Restaurant } from '../models';
import { RestaurantApi } from '../services/restaurant-api';
import { Session } from '../services/session';
import { AppFooter } from '../shared/app-footer/app-footer';
import { AppHeader } from '../shared/app-header/app-header';

@Component({
  imports: [RouterLink, AppHeader, AppFooter],
  selector: 'app-swipe',
  styleUrl: './swipe.css',
  templateUrl: './swipe.html',
  host: { '(window:keydown)': 'onKey($event)' },
})
export class Swipe {
  private api = inject(RestaurantApi);
  private session = inject(Session);
  private router = inject(Router);

  code = (inject(ActivatedRoute).snapshot.paramMap.get('code') ?? '').toUpperCase();
  me = this.session.get(this.code);

  cards = signal<Restaurant[]>([]);
  current = computed(() => this.cards()[0] ?? null);
  done = signal(0);
  total = signal(0);
  group = signal<Group | null>(null);
  matchCount = signal(0);
  loading = signal(true);
  finished = signal(false);
  busy = signal(false);
  error = signal('');
  brokenImages = signal(new Set<number>());
  private cardsLoaded = false;

  pretty = pretty;
  gradient = cuisineGradient;
  initials = initials;

  myName = computed(() => this.group()?.members.find((m) => m.id === this.me?.id)?.name ?? null);
  /** a restaurant's 1st cuisine, e.g. "Mediterranean" */
  cuisineOf(r: Restaurant) {
    return r.cuisines?.length ? pretty(r.cuisines[0]) : '';
  }
  percent(swiped: number) {
    return this.total() ? Math.min(100, Math.round((swiped / this.total()) * 100)) : 0;
  }
  allDone = computed(() => !!this.total() && (this.group()?.members ?? []).every((m) => m.swiped >= this.total()));

  constructor() {
    if (this.me === null) {
      this.router.navigate(['/join', this.code]);
      return;
    }
    // Everyone's progress + match count, refreshed every 5 seconds (names and counts only).
    timer(0, 5000)
      .pipe(
        switchMap(() =>
          forkJoin({ g: this.api.getGroup(this.code), m: this.api.getMatches(this.code) }).pipe(
            catchError(() => {
              this.error.set("Couldn't load the group.");
              this.loading.set(false);
              return EMPTY;
            }),
          ),
        ),
        takeUntilDestroyed(),
      )
      .subscribe(({ g, m }) => {
        this.group.set(g);
        this.matchCount.set(m.matches.length);
        if (!g.started) {
          this.router.navigate(['/group', this.code]);
          return;
        }
        if (!this.cardsLoaded) {
          this.cardsLoaded = true;
          this.loadCards();
        }
      });
  }

  private loadCards() {
    this.api.getNextCards(this.me!).subscribe({
      next: (r) => {
        this.cards.set(r.cards);
        this.done.set(r.done);
        this.total.set(r.total);
        this.finished.set(r.cards.length === 0);
        this.loading.set(false);
      },
      error: () => {
        this.error.set("Couldn't load restaurants. Is the Django server running?");
        this.loading.set(false);
      },
    });
  }

  onKey(e: KeyboardEvent) {
    if (e.key === 'ArrowRight') this.vote(true);
    if (e.key === 'ArrowLeft') this.vote(false);
  }

  imageFailed(id: number) {
    this.brokenImages.update((s) => new Set(s).add(id));
  }

  vote(liked: boolean) {
    const card = this.current();
    if (!card || this.busy()) return;
    this.busy.set(true);
    this.error.set('');
    this.api.swipe(this.me!, card.id, liked).subscribe({
      next: () => {
        this.busy.set(false);
        const rest = this.cards().slice(1);
        this.cards.set(rest);
        this.done.update((d) => d + 1);
        // optimistic: bump my own count so the progress bar moves immediately
        this.group.update((g) =>
          g ? { ...g, members: g.members.map((m) => (m.id === this.me!.id ? { ...m, swiped: m.swiped + 1 } : m)) } : g,
        );
        if (rest.length === 0) this.loadCards(); // next batch of the shared deck, or finish
      },
      error: () => {
        this.error.set("Couldn't save that swipe. Try again.");
        this.busy.set(false);
      },
    });
  }
}