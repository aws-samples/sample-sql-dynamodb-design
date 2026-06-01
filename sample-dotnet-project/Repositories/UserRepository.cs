using Microsoft.EntityFrameworkCore;
using ECommerceApp.Data;
using ECommerceApp.Models;

namespace ECommerceApp.Repositories;

public class UserRepository
{
    private readonly AppDbContext _db;
    public UserRepository(AppDbContext db) => _db = db;

    public async Task<User?> GetByIdAsync(Guid userId)
    {
        return await _db.Users
            .Include(u => u.Profile)
            .Include(u => u.Addresses)
            .FirstOrDefaultAsync(u => u.Id == userId);
    }

    public async Task<User?> GetByEmailAsync(string email)
    {
        return await _db.Users
            .Where(u => u.Email == email && u.IsActive)
            .Select(u => new User
            {
                Id = u.Id,
                Email = u.Email,
                PasswordHash = u.PasswordHash,
                IsActive = u.IsActive
            })
            .FirstOrDefaultAsync();
    }

    public async Task<User?> GetByUsernameAsync(string username)
    {
        return await _db.Users
            .Include(u => u.Profile)
            .Where(u => u.Username == username)
            .FirstOrDefaultAsync();
    }

    public async Task<List<User>> SearchUsersAsync(string query, int page = 1, int pageSize = 20)
    {
        return await _db.Users
            .Where(u => u.FirstName.Contains(query)
                     || u.LastName.Contains(query)
                     || u.Email.Contains(query))
            .OrderBy(u => u.LastName)
            .ThenBy(u => u.FirstName)
            .Skip((page - 1) * pageSize)
            .Take(pageSize)
            .Select(u => new User
            {
                Id = u.Id,
                Email = u.Email,
                FirstName = u.FirstName,
                LastName = u.LastName,
                IsActive = u.IsActive,
                CreatedDate = u.CreatedDate
            })
            .ToListAsync();
    }

    public async Task<User> CreateAsync(User user)
    {
        _db.Users.Add(user);
        await _db.SaveChangesAsync();
        return user;
    }

    public async Task UpdateAsync(User user)
    {
        _db.Users.Update(user);
        await _db.SaveChangesAsync();
    }

    public async Task<int> GetTotalCountAsync()
    {
        return await _db.Users.CountAsync(u => u.IsActive);
    }

    public async Task<List<User>> GetRecentUsersAsync(int days = 30)
    {
        var since = DateTime.UtcNow.AddDays(-days);
        return await _db.Users
            .Where(u => u.CreatedDate >= since)
            .OrderByDescending(u => u.CreatedDate)
            .ToListAsync();
    }
}
