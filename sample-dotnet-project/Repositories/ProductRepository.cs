using Microsoft.EntityFrameworkCore;
using ECommerceApp.Data;
using ECommerceApp.Models;

namespace ECommerceApp.Repositories;

public class ProductRepository
{
    private readonly AppDbContext _db;
    public ProductRepository(AppDbContext db) => _db = db;

    public async Task<Product?> GetByIdAsync(int productId)
    {
        return await _db.Products
            .Include(p => p.Category)
            .Include(p => p.Reviews.OrderByDescending(r => r.CreatedDate).Take(5))
            .Include(p => p.Inventory)
            .FirstOrDefaultAsync(p => p.Id == productId);
    }

    public async Task<Product?> GetBySKUAsync(string sku)
    {
        return await _db.Products
            .FirstOrDefaultAsync(p => p.SKU == sku);
    }

    public async Task<List<Product>> GetByCategoryAsync(int categoryId, int page = 1, int pageSize = 20)
    {
        return await _db.Products
            .Where(p => p.CategoryId == categoryId && p.IsActive)
            .OrderByDescending(p => p.CreatedDate)
            .Skip((page - 1) * pageSize)
            .Take(pageSize)
            .Select(p => new Product
            {
                Id = p.Id,
                Name = p.Name,
                Price = p.Price,
                ThumbnailUrl = p.ThumbnailUrl,
                AverageRating = p.AverageRating
            })
            .ToListAsync();
    }

    public async Task<List<Product>> GetByCategoryPriceSortedAsync(
        int categoryId, decimal? minPrice, decimal? maxPrice, bool ascending = true)
    {
        var query = _db.Products
            .Where(p => p.CategoryId == categoryId && p.IsActive);

        if (minPrice.HasValue)
            query = query.Where(p => p.Price >= minPrice.Value);
        if (maxPrice.HasValue)
            query = query.Where(p => p.Price <= maxPrice.Value);

        query = ascending
            ? query.OrderBy(p => p.Price)
            : query.OrderByDescending(p => p.Price);

        return await query
            .Select(p => new Product
            {
                Id = p.Id,
                Name = p.Name,
                Price = p.Price,
                ThumbnailUrl = p.ThumbnailUrl
            })
            .ToListAsync();
    }

    public async Task<List<Product>> SearchAsync(string searchTerm)
    {
        return await _db.Products
            .Include(p => p.Category)
            .Where(p => p.IsActive &&
                       (p.Name.Contains(searchTerm) || p.Description.Contains(searchTerm)))
            .Select(p => new Product
            {
                Id = p.Id,
                Name = p.Name,
                Price = p.Price,
                ThumbnailUrl = p.ThumbnailUrl,
                Category = new Category { Name = p.Category.Name }
            })
            .ToListAsync();
    }

    public async Task<List<Product>> GetTopRatedAsync(int count = 10)
    {
        return await _db.Products
            .Where(p => p.IsActive && p.AverageRating >= 4.0)
            .OrderByDescending(p => p.AverageRating)
            .Take(count)
            .Select(p => new Product
            {
                Id = p.Id,
                Name = p.Name,
                Price = p.Price,
                ThumbnailUrl = p.ThumbnailUrl,
                AverageRating = p.AverageRating
            })
            .ToListAsync();
    }

    public async Task<List<Product>> GetRelatedProductsAsync(int productId, int count = 5)
    {
        var product = await _db.Products.FindAsync(productId);
        if (product == null) return new List<Product>();

        return await _db.Products
            .Where(p => p.CategoryId == product.CategoryId && p.Id != productId && p.IsActive)
            .OrderByDescending(p => p.AverageRating)
            .Take(count)
            .ToListAsync();
    }
}
