import { Service } from '@angular/core';

/**
 * Remembers which member "you" are in each group, in this browser only.
 * (There are no logins: the member id is saved in localStorage.)
 */
@Service()
export class Session {
  private key(code: string) {
    return `menuswipe.member.${code.toUpperCase()}`;
  }

  getMemberId(code: string): number | null {
    try {
      const v = localStorage.getItem(this.key(code));
      return v ? Number(v) : null;
    } catch {
      return null; // storage can be blocked; the app should still work
    }
  }

  saveMemberId(code: string, id: number): void {
    try {
      localStorage.setItem(this.key(code), String(id));
    } catch {
      /* ignore */
    }
  }
}