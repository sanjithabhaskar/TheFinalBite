import { Component, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Router } from '@angular/router';
import { CUISINE_OPTIONS, DIETARY_OPTIONS, Group, pretty } from '../models';
import { RestaurantApi } from '../services/restaurant-api';
import { Session } from '../services/session';
import { AppHeader } from '../shared/app-header/app-header';

@Component({
  imports: [FormsModule, AppHeader],
  selector: 'app-home',
  styleUrl: './home.css',
  templateUrl: './home.html',
})
export class Home {
  private api = inject(RestaurantApi);
  private session = inject(Session);
  private router = inject(Router);

  tab = signal<'create' | 'join'>('create');

  // create form (you become the host)
  name = signal('');
  groupName = signal('');
  budget = signal<number | null>(null);
  dietary = signal<string[]>([]);
  cuisines = signal<string[]>([]);
  showAllDiet = signal(false);
  showAllCuisines = signal(false);
  busy = signal(false);
  error = signal('');

  // join tab
  code = signal('');
  codeState = signal<'idle' | 'checking' | 'valid' | 'invalid'>('idle');
  preview = signal<Group | null>(null);

  pretty = pretty;
  // The Figma shows the first five; "More" reveals the rest.
  dietaryShort = ['vegan', 'vegetarian', 'gluten_free', 'dairy_free', 'halal'];
  dietaryAll = DIETARY_OPTIONS;
  cuisinesShort = ['mediterranean', 'italian', 'japanese', 'mexican'];
  cuisinesAll = CUISINE_OPTIONS;

  toggle(list: ReturnType<typeof signal<string[]>>, value: string) {
    list.update((l) => (l.includes(value) ? l.filter((v) => v !== value) : [...l, value]));
  }

  canCreate() {
    return this.name().trim().length > 0 && (this.budget() ?? 0) > 0 && !this.busy();
  }

  /** Create the group, then join it as the first member (= host), then go to the lobby. */
  createGroup() {
    if (!this.canCreate()) return;
    this.busy.set(true);
    this.error.set('');
    this.api.createGroup(this.groupName().trim()).subscribe({
      next: (group) => {
        this.api
          .joinGroup(group.invite_code, {
            name: this.name().trim(),
            max_entree_budget: this.budget()!,
            dietary_restrictions: this.dietary(),
            cuisine_prefs: this.cuisines(),
          })
          .subscribe({
            next: (me) => {
              this.session.save(group.invite_code, { id: me.id, token: me.token });
              this.router.navigate(['/group', group.invite_code]);
            },
            error: (e) => this.fail(e?.error?.detail ?? "Couldn't set up your profile. Check your details."),
          });
      },
      error: () => this.fail("Couldn't create the group. Is the Django server running?"),
    });
  }

  private fail(msg: string) {
    this.error.set(msg);
    this.busy.set(false);
  }

  onCode(value: string) {
    const c = value.trim().toUpperCase();
    this.code.set(c);
    this.preview.set(null);
    if (c.length < 6) {
      this.codeState.set('idle');
      return;
    }
    this.codeState.set('checking');
    this.api.getGroup(c).subscribe({
      next: (g) => {
        if (this.code() !== c) return;
        this.preview.set(g);
        this.codeState.set('valid');
      },
      error: () => {
        if (this.code() === c) this.codeState.set('invalid');
      },
    });
  }

  goToCode() {
    if (this.codeState() === 'valid') this.router.navigate(['/join', this.code()]);
  }
}