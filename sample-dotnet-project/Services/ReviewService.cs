using ECommerceApp.Data;
using ECommerceApp.Models;
using ECommerceApp.Repositories;

namespace ECommerceApp.Services;

public class ReviewService
{
    private readonly AppDbContext _db;
    private readonly ReviewRepository _reviewRepo;
    private readonly OrderRepository _orderRepo;

    public ReviewService(AppDbContext db, ReviewRepository reviewRepo, OrderRepository orderRepo)
    {
        _db = db;
        _reviewRepo = reviewRepo;
        _orderRepo = orderRepo;
    }

    public async Task<Review> SubmitReviewAsync(Guid userId, int productId, int rating, string? title, string? comment)
    {
        if (await _reviewRepo.HasUserReviewedAsync(userId, productId))
            throw new InvalidOperationException("User already reviewed this product");

        // Check if user purchased the product
        var userOrders = await _orderRepo.GetByUserIdAsync(userId, 1, 100);
        var hasPurchased = userOrders
            .Any(o => o.Status == OrderStatus.Delivered &&
                      o.Items.Any(i => i.ProductId == productId));

        var review = new Review
        {
            Id = Guid.NewGuid(),
            ProductId = productId,
            UserId = userId,
            Rating = rating,
            Title = title,
            Comment = comment,
            IsVerifiedPurchase = hasPurchased,
            CreatedDate = DateTime.UtcNow
        };

        await _reviewRepo.CreateAsync(review);

        // Update product average rating
        var (avgRating, count) = await _reviewRepo.GetAverageRatingAsync(productId);
        var product = await _db.Products.FindAsync(productId);
        if (product != null)
        {
            product.AverageRating = avgRating;
            product.ReviewCount = count;
            await _db.SaveChangesAsync();
        }

        return review;
    }
}
