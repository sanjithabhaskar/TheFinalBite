import { Component, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, Router } from '@angular/router';
import { CUISINE_OPTIONS, DIETARY_OPTIONS, Group, pretty } from '../models';
import { RestaurantApi } from '../services/restaurant-api';
import { Session } from '../services/session';

@Component({
  imports: [FormsModule],
  selector: 'app-join',
  styleUrl: './join.css',
  templateUrl: './join.html',
})
export class Join {
  private api = inject(RestaurantApi);
  private session = inject(Session);
  private router = inject(Router);

  code = (inject(ActivatedRoute).snapshot.paramMap.get('code') ?? '').toUpperCase();

  group = signal<Group | null>(null);
  notFound = signal(false);

  // form state: signals work directly with [(ngModel)]
  name = signal('');
  budget = signal<number | null>(25);
  dietary = signal<string[]>([]);
  cuisines = signal<string[]>([]);

  busy = signal(false);
  error = signal('');

  dietaryOptions = DIETARY_OPTIONS;
  cuisineOptions = CUISINE_OPTIONS;
  pretty = pretty;

  constructor() {
    // Already joined this group on this browser? Skip the form.
    if (this.session.getMemberId(this.code) !== null) {
      this.router.navigate(['/group', this.code]);
      return;
    }
    this.api.getGroup(this.code).subscribe({
      next: (g) => this.group.set(g),
      error: () => this.notFound.set(true),
    });
  }

  toggle(list: ReturnType<typeof signal<string[]>>, value: string) {
    list.update((l) => (l.includes(value) ? l.filter((v) => v !== value) : [...l, value]));
  }

  canSubmit() {
    return this.name().trim().length > 0 && (this.budget() ?? 0) > 0 && !this.busy();
  }

  submit() {
    if (!this.canSubmit()) return;
    this.busy.set(true);
    this.error.set('');
    this.api
      .joinGroup(this.code, {
        name: this.name().trim(),
        max_entree_budget: this.budget()!,
        dietary_restrictions: this.dietary(),
        cuisine_prefs: this.cuisines(),
      })
      .subscribe({
        next: (member) => {
          this.session.saveMemberId(this.code, member.id);
          this.router.navigate(['/group', this.code]);
        },
        error: (e) => {
          this.error.set(e?.error?.detail ?? "Couldn't join the group. Check your details and try again.");
          this.busy.set(false);
        },
      });
  }
}