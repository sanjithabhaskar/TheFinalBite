import { Component, input } from '@angular/core';
import { initials } from '../../models';

/** Top bar from the Figma: logo, 3-step tracker, and on the right either the tagline or who you are. */
@Component({
  selector: 'app-header',
  template: `
    <header>
      <a class="logo" href="/">
        <span class="mark">
          <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="#fff" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <path d="M6 3v7a2 2 0 0 0 2 2v9M10 3v7M6 3v7M18 3c-2 1.5-3 4-3 7h3v11" />
          </svg>
        </span>
        <span class="name">The Final Bite</span>
      </a>

      <ol class="steps">
        @for (s of steps; track s.n) {
          <li [class.on]="step() === s.n" [class.done]="step() > s.n">
            <span class="dot">{{ s.n }}</span>
            <span class="label">{{ s.label }}</span>
          </li>
        }
      </ol>

      @if (user(); as u) {
        <span class="me"><span class="avatar">{{ initials(u) }}</span><span class="who">{{ u }}</span></span>
      } @else {
        <span class="tagline">Good food. Great company.</span>
      }
    </header>
  `,
  styles: `
    header { display: grid; grid-template-columns: 1fr auto 1fr; align-items: center; padding: clamp(10px, 1.8vh, 18px) clamp(24px, 4.4vw, 64px); border-bottom: 1px solid var(--line); background: var(--bg); }
    .logo { display: flex; align-items: center; gap: 10px; text-decoration: none; color: var(--ink); }
    .mark { width: 34px; height: 34px; border-radius: 9px; background: var(--accent); display: grid; place-items: center; }
    .name { font-family: var(--serif); font-size: 24px; }
    .steps { display: flex; gap: 28px; list-style: none; margin: 0; padding: 0; }
    .steps li { display: flex; align-items: center; gap: 8px; color: var(--muted); font-size: 14px; }
    .dot { width: 24px; height: 24px; border-radius: 50%; background: #ece5d8; display: grid; place-items: center; font-size: 12px; font-weight: 600; }
    li.on { color: var(--ink); font-weight: 600; }
    li.on .dot, li.done .dot { background: var(--accent); color: #fff; }
    .tagline { justify-self: end; color: var(--muted); font-size: 14px; }
    .me { justify-self: end; display: flex; align-items: center; gap: 10px; font-size: 14px; font-weight: 600; }
    @media (max-width: 900px) {
      header { grid-template-columns: 1fr auto; gap: 12px; padding: 14px 20px; }
      .steps { grid-column: 1 / -1; order: 3; gap: 14px; justify-content: space-between; }
      .tagline { display: none; }
      .label { display: none; }
      li.on .label { display: inline; }
    }
  `,
})
export class AppHeader {
  step = input<number>(1);
  user = input<string | null>(null);
  initials = initials;
  steps = [
    { n: 1, label: 'Your preferences' },
    { n: 2, label: 'Gather your group' },
    { n: 3, label: 'Swipe & agree' },
  ];
}