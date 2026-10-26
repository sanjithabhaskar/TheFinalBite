import { Component, inject, signal } from '@angular/core';
import { RestaurantApi } from '../services/restaurant-api';
import { Restaurant } from '../models';

@Component({
  imports: [],
  selector: 'app-restaurant-list',
  styleUrl: './restaurant-list.css',
  templateUrl: './restaurant-list.html',
})
export class RestaurantList {
  private api = inject(RestaurantApi);

  restaurants = signal<Restaurant[]>([]);
  loading = signal(true);
  error = signal('');

  constructor() {
    this.api.getRestaurants().subscribe({
      next: (data) => {
        this.restaurants.set(data);
        this.loading.set(false);
      },
      error: () => {
        this.error.set("Couldn't load restaurants. Is the Django server running?");
        this.loading.set(false);
      },
    });
  }
}