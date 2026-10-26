import { Component } from '@angular/core';

@Component({
  selector: 'app-footer',
  template: `<footer><span>Decide where to eat, together.</span><span>A little less "where should we eat?"</span></footer>`,
  styles: `footer { display: flex; justify-content: space-between; padding: 22px 64px; border-top: 1px solid var(--line); color: var(--muted); font-size: 14px; }
    @media (max-width: 960px) { footer { flex-direction: column; gap: 6px; padding: 18px 20px; } }`,
})
export class AppFooter {}