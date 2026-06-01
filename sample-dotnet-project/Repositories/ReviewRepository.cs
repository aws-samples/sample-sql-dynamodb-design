using Microsoft.EntityFrameworkCore;
using ECommerceApp.Data;
using ECommerceApp.Models;

namespace ECommerceApp.Repositories;

public class ReviewRepository
{
    private readonly AppDbContext _db;
    public ReviewRepository(AppDbContext db) => _db = db;

    public async Task<List<Review>> GetByProductIdAsync(int productId, int page = 1, int pageSize = 10)
    {
        return await _db.Reviews
            .Include(r => r.User)
            .Where(r => r.ProductId == productId)
            .OrderByDescending(r => r.CreatedDate)
            .Skip((page - 1) * pageSize)
            .Take(pageSize)
            .Select(r => new Review
            {
                Id = r.Id,
                Rating = r.Rating,
                Title = r.Title,
                Comment = r.Comment,
                UserName = r.User.Username,
                IsVerifiedPurchase = r.IsVerifiedPurchase,
                CreatedDate = r.CreatedDate
            })
            .ToListAsync();
    }

    public async Task<List<Review>> GetByUserIdAsync(Guid userId)
    {
        return await _db.Reviews
            .Include(r => r.Product)
            .Where(r => r.UserId == userId)
            .OrderByDescending(r => r.CreatedDate)
            .Select(r => new Review
            {
                Id = r.Id,
                Rating = r.Rating,
                Comment = r.Comment,
                ProductId = r.ProductId,
                CreatedDate = r.CreatedDate,
                Product = new Product { Name = r.Product.Name, ThumbnailUrl = r.Product.ThumbnailUrl }
            })
            .ToListAsync();
    }

    public async Task<(double avgRating, int count)> GetAverageRatingAsync(int productId)
    {
        var stats = await _db.Reviews
            .Where(r => r.ProductId == productId)
            .GroupBy(r => r.ProductId)
            .Select(g => new
            {
                Average = g.Average(r => r.Rating),
                Count = g.Count()
            })
            .FirstOrDefaultAsync();

        return stats != null ? (stats.Average, stats.Count) : (0, 0);
    }

    public async Task<bool> HasUserReviewedAsync(Guid userId, int productId)
    {
        return await _db.Reviews
            .AnyAsync(r => r.UserId == userId && r.ProductId == productId);
    }

    public async Task<Review> CreateAsync(Review review)
    {
        _db.Reviews.Add(review);
        await _db.SaveChangesAsync();
        return review;
    }
}
