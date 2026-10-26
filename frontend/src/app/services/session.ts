import { Service } from '@angular/core';

export interface Me {
  id: number;
  token: string;
}

/**
 * Remembers who "you" are in each group, in this browser only.
 * The token is your private key: the server only shows your budget and diet to someone holding it.
 */
@Service()
export class Session {
  private key(code: string) {
    return `finalbite.member.${code.toUpperCase()}`;
  }

  get(code: string): Me | null {
    try {
      const v = localStorage.getItem(this.key(code));
      return v ? (JSON.parse(v) as Me) : null;
    } catch {
      return null; // storage can be blocked; the app should still work
    }
  }

  save(code: string, me: Me): void {
    try {
      localStorage.setItem(this.key(code), JSON.stringify(me));
    } catch {
      /* ignore */
    }
  }
}