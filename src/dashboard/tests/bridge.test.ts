// src/dashboard/tests/bridge.test.ts
import { login, logout, getSessions, getAgents, getModels } from '../api/bridge';

global.fetch = jest.fn();

describe('API Bridge', () => {
  beforeEach(() => {
    (fetch as jest.Mock).mockClear();
    localStorage.clear();
  });

  it('handles login and token storage', async () => {
    (fetch as jest.Mock).mockResolvedValueOnce({
      ok: true,
      json: async () => ({ token: 'abc123' }),
      status: 200,
    });
    const res = await login('user', 'pass');
    expect(res.data?.token).toBe('abc123');
    expect(localStorage.getItem('chimera_token')).toBe('abc123');
  });

  it('handles failed login', async () => {
    (fetch as jest.Mock).mockResolvedValueOnce({
      ok: false,
      json: async () => ({ message: 'Invalid' }),
      status: 401,
      statusText: 'Unauthorized',
    });
    const res = await login('user', 'wrong');
    expect(res.error?.status).toBe(401);
    expect(res.error?.message).toBe('Invalid');
  });

  it('fetches sessions and normalizes', async () => {
    (fetch as jest.Mock).mockResolvedValueOnce({
      ok: true,
      json: async () => [
        { id: '1', user: 'a', createdAt: '2024-01-01', active: true },
        { id: '2', user: 'b', createdAt: '2025-01-01', active: false },
      ],
      status: 200,
    });
    const res = await getSessions();
    expect(res.data?.[0].id).toBe('2'); // Sorted by createdAt desc
  });

  it('handles network error', async () => {
    (fetch as jest.Mock).mockRejectedValueOnce(new Error('Network down'));
    const res = await getSessions();
    expect(res.error?.message).toMatch(/Network/);
  });
});
