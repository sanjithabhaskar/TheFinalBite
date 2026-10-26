import { Component, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { ActivatedRoute, Router } from '@angular/router';
import { catchError, EMPTY, switchMap, timer } from 'rxjs';
import { CUISINE_OPTIONS, DIETARY_OPTIONS, Group, initials, pretty } from '../models';
import { AppFooter } from '../shared/app-footer/app-footer';
import { AppHeader } from '../shared/app-header/app-header';
import { RestaurantApi } from '../services/restaurant-api';
import { Session } from '../services/session';

@Component({
  imports: [FormsModule, AppHeader, AppFooter],
  selector: 'app-group-lobby',
  styleUrl: './group-lobby.css',
  templateUrl: './group-lobby.html',
})
export class GroupLobby {
  private api = inject(RestaurantApi);
  private session = inject(Session);
  private router = inject(Router);

  code = (inject(ActivatedRoute).snapshot.paramMap.get('code') ?? '').toUpperCase();
  me = this.session.get(this.code);
  myId = this.me?.id ?? null;

  group = signal<Group | null>(null);
  error = signal('');
  startError = signal('');
  copied = signal(false);
  starting = signal(false);
  pretty = pretty;
  initials = initials;
  dietaryOptions = DIETARY_OPTIONS;
  cuisineOptions = CUISINE_OPTIONS;

  // "Edit my preferences" (only you can see/change these)
  editing = signal(false);
  saving = signal(false);
  saved = signal(false);
  editBudget = signal<number | null>(null);
  editDietary = signal<string[]>([]);
  editCuisines = signal<string[]>([]);

  openEdit() {
    if (this.me === null) return;
    this.api.getMe(this.me).subscribe({
      next: (m) => {
        this.editBudget.set(Number(m.max_entree_budget));
        this.editDietary.set(m.dietary_restrictions);
        this.editCuisines.set(m.cuisine_prefs);
        this.saved.set(false);
        this.editing.set(true);
      },
      error: () => this.startError.set("Couldn't load your preferences."),
    });
  }

  toggle(list: ReturnType<typeof signal<string[]>>, value: string) {
    list.update((l) => (l.includes(value) ? l.filter((v) => v !== value) : [...l, value]));
  }

  saveEdit() {
    if (this.me === null || !(this.editBudget() && this.editBudget()! > 0)) return;
    this.saving.set(true);
    this.api
      .updateMe(this.me, {
        max_entree_budget: this.editBudget()!,
        dietary_restrictions: this.editDietary(),
        cuisine_prefs: this.editCuisines(),
      })
      .subscribe({
        next: () => {
          this.saving.set(false);
          this.saved.set(true);
          this.editing.set(false);
        },
        error: (e) => {
          this.saving.set(false);
          this.startError.set(e?.error?.detail ?? "Couldn't save your changes.");
        },
      });
  }

  inviteLink = `${window.location.origin}/join/${this.code}`;

  constructor() {
    // You haven't joined on this browser: send to the join form.
    if (this.me === null) {
      this.router.navigate(['/join', this.code]);
      return;
    }
    // Refresh every 5 seconds. Stops automatically when you leave the page.
    timer(0, 5000)
      .pipe(
        switchMap(() =>
          this.api.getGroup(this.code).pipe(
            catchError(() => {
              this.error.set("Couldn't load the group.");
              return EMPTY;
            }),
          ),
        ),
        takeUntilDestroyed(),
      )
      .subscribe((g) => {
        this.error.set('');
        this.group.set(g);
        // Once the host starts, everyone moves on to swiping.
        if (g.started) this.router.navigate(['/swipe', this.code]);
      });
  }

  myName() {
    return this.group()?.members.find((m) => m.id === this.myId)?.name ?? null;
  }

  /** Names of everyone except you, e.g. "Alex" or "Alex and Max". */
  othersText() {
    const names = (this.group()?.members ?? []).filter((m) => m.id !== this.myId).map((m) => m.name);
    return names.length > 1 ? names.slice(0, -1).join(', ') + ' and ' + names[names.length - 1] : (names[0] ?? '');
  }

  isHost() {
    return this.group()?.host_member_id === this.myId;
  }

  start() {
    if (this.me === null) return;
    this.starting.set(true);
    this.startError.set('');
    this.api.startGroup(this.code, this.me).subscribe({
      next: () => this.router.navigate(['/swipe', this.code]),
      error: (e) => {
        this.startError.set(e?.error?.detail ?? "Couldn't start swiping.");
        this.starting.set(false);
      },
    });
  }

  async copyLink() {
    try {
      await navigator.clipboard.writeText(this.inviteLink);
      this.copied.set(true);
      setTimeout(() => this.copied.set(false), 2000);
    } catch {
      /* clipboard blocked: the link is visible to copy by hand */
    }
  }
}