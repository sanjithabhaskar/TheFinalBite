import { Component, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Router } from '@angular/router';
import { RestaurantApi } from '../services/restaurant-api';

@Component({
  imports: [FormsModule],
  selector: 'app-home',
  styleUrl: './home.css',
  templateUrl: './home.html',
})
export class Home {
  private api = inject(RestaurantApi);
  private router = inject(Router);

  groupName = signal('');
  code = signal('');
  busy = signal(false);
  error = signal('');

  createGroup() {
    this.busy.set(true);
    this.error.set('');
    this.api.createGroup(this.groupName().trim()).subscribe({
      next: (group) => this.router.navigate(['/join', group.invite_code]),
      error: () => {
        this.error.set("Couldn't create the group. Is the Django server running?");
        this.busy.set(false);
      },
    });
  }

  goToCode() {
    const c = this.code().trim().toUpperCase();
    if (c) this.router.navigate(['/join', c]);
  }
}
