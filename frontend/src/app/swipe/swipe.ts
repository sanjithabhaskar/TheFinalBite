import { Component, computed, inject, signal } from '@angular/core';
import { ActivatedRoute, Router, RouterLink } from '@angular/router';
import { pretty, Restaurant } from '../models';
import { RestaurantApi } from '../services/restaurant-api';
import { Session } from '../services/session';

@Component({
  imports: [RouterLink],
  selector: 'app-swipe',
  styleUrl: './swipe.css',
  templateUrl: './swipe.html',
})
export class Swipe {
  private api = inject(RestaurantApi);
  private session = inject(Session);
  private router = inject(Router);

  code = (inject(ActivatedRoute).snapshot.paramMap.get('code') ?? '').toUpperCase();
  myId = this.session.getMemberId(this.code);

  cards = signal<Restaurant[]>([]);
  current = computed(() => this.cards()[0] ?? null);
  loading = signal(true);
  finished = signal(false);
  busy = signal(false);
  error = signal('');
  pretty = pretty;

  constructor() {
    if (this.myId === null) {
      this.router.navigate(['/join', this.code]);
      return;
    }
    // Only allowed once the host has started.
    this.api.getGroup(this.code).subscribe({
      next: (g) => {
        if (!g.started) this.router.navigate(['/group', this.code]);
        else this.loadCards();
      },
      error: () => {
        this.error.set("Couldn't load the group.");
        this.loading.set(false);
      },
    });
  }

  private loadCards() {
    this.api.getNextCards(this.myId!).subscribe({
      next: (cards) => {
        this.cards.set(cards);
        this.finished.set(cards.length === 0);
        this.loading.set(false);
      },
      error: () => {
        this.error.set("Couldn't load restaurants. Is the Django server running?");
        this.loading.set(false);
      },
    });
  }

  vote(liked: boolean) {
    const card = this.current();
    if (!card || this.busy()) return;
    this.busy.set(true);
    this.error.set('');
    this.api.swipe(this.myId!, card.id, liked).subscribe({
      next: () => {
        this.busy.set(false);
        const rest = this.cards().slice(1);
        this.cards.set(rest);
        if (rest.length === 0) this.loadCards(); // fetch the next batch (or finish)
      },
      error: () => {
        this.error.set("Couldn't save that swipe. Try again.");
        this.busy.set(false);
      },
    });
  }
}
