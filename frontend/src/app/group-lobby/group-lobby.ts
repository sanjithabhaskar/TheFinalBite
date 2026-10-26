import { Component, inject, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { ActivatedRoute, Router } from '@angular/router';
import { catchError, EMPTY, switchMap, timer } from 'rxjs';
import { Group, pretty } from '../models';
import { RestaurantApi } from '../services/restaurant-api';
import { Session } from '../services/session';

@Component({
  imports: [],
  selector: 'app-group-lobby',
  styleUrl: './group-lobby.css',
  templateUrl: './group-lobby.html',
})
export class GroupLobby {
  private api = inject(RestaurantApi);
  private session = inject(Session);
  private router = inject(Router);

  code = (inject(ActivatedRoute).snapshot.paramMap.get('code') ?? '').toUpperCase();
  myId = this.session.getMemberId(this.code);

  group = signal<Group | null>(null);
  error = signal('');
  copied = signal(false);
  starting = signal(false);
  pretty = pretty;

  inviteLink = `${window.location.origin}/join/${this.code}`;

  constructor() {
    // You haven't joined on this browser: send to the join form.
    if (this.myId === null) {
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

  isHost() {
    return this.group()?.host_member_id === this.myId;
  }

  start() {
    if (this.myId === null) return;
    this.starting.set(true);
    this.api.startGroup(this.code, this.myId).subscribe({
      next: () => this.router.navigate(['/swipe', this.code]),
      error: () => {
        this.error.set("Couldn't start swiping. Only the host can do that.");
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