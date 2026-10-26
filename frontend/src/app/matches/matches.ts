import { Component, computed, inject, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { catchError, EMPTY, forkJoin, switchMap, timer } from 'rxjs';
import { cuisineGradient, Group, initials, MatchesResponse, pretty, Restaurant } from '../models';
import { RestaurantApi } from '../services/restaurant-api';
import { Session } from '../services/session';
import { AppFooter } from '../shared/app-footer/app-footer';
import { AppHeader } from '../shared/app-header/app-header';

@Component({
  imports: [RouterLink, AppHeader, AppFooter],
  selector: 'app-matches',
  styleUrl: './matches.css',
  templateUrl: './matches.html',
})
export class Matches {
  private api = inject(RestaurantApi);
  private session = inject(Session);

  code = (inject(ActivatedRoute).snapshot.paramMap.get('code') ?? '').toUpperCase();
  me = this.session.get(this.code);
  data = signal<MatchesResponse | null>(null);
  group = signal<Group | null>(null);
  error = signal('');
  copied = signal(false);
  brokenImages = signal(new Set<number>());

  pretty = pretty;
  gradient = cuisineGradient;
  initials = initials;

  myName = computed(() => this.group()?.members.find((m) => m.id === this.me?.id)?.name ?? null);
  members = computed(() => this.group()?.members ?? []);
  deck = computed(() => this.group()?.deck_size ?? 0);
  everyoneFinished = computed(() => this.members().length > 0 && this.members().every((m) => m.swiped >= this.deck()));
  waitingOn = computed(() => this.members().filter((m) => m.swiped < this.deck()).map((m) => m.name).join(', '));
  names = computed(() => this.members().map((m) => m.name).join(' + '));

  constructor() {
    // Refresh every 5 seconds so new matches appear as other people swipe.
    timer(0, 5000)
      .pipe(
        switchMap(() =>
          forkJoin({ m: this.api.getMatches(this.code), g: this.api.getGroup(this.code) }).pipe(
            catchError(() => {
              this.error.set("Couldn't load matches.");
              return EMPTY;
            }),
          ),
        ),
        takeUntilDestroyed(),
      )
      .subscribe(({ m, g }) => {
        this.error.set('');
        this.data.set(m);
        this.group.set(g);
      });
  }

  cuisineOf(r: Restaurant) {
    return r.cuisines?.length ? pretty(r.cuisines[0]) : '';
  }
  /** "vegan" -> "Vegan options" */
  optionLabel(tag: string) {
    return pretty(tag) + ' options';
  }
  imageFailed(id: number) {
    this.brokenImages.update((s) => new Set(s).add(id));
  }

  async share() {
    const d = this.data();
    if (!d) return;
    const lines = d.matches.map((r) => `• ${r.name} (${r.neighborhood ?? ''}, about $${r.median_entree_price} an entrée)`);
    const text = `Our matches on The Final Bite:\n${lines.join('\n')}`;
    try {
      await navigator.clipboard.writeText(text);
      this.copied.set(true);
      setTimeout(() => this.copied.set(false), 2000);
    } catch {
      /* clipboard blocked */
    }
  }
}