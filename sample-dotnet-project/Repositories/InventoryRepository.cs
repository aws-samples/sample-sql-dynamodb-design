using Microsoft.EntityFrameworkCore;
using ECommerceApp.Data;
using ECommerceApp.Models;

namespace ECommerceApp.Repositories;

public class InventoryRepository
{
    private readonly AppDbContext _db;
    public InventoryRepository(AppDbContext db) => _db = db;

    public async Task<Inventory?> GetByProductIdAsync(int productId)
    {
        return await _db.Inventory
            .FirstOrDefaultAsync(i => i.ProductId == productId);
    }

    public async Task<List<Inventory>> GetLowStockAsync(int threshold = 10)
    {
        return await _db.Inventory
            .Include(i => i.Product)
            .Where(i => i.Quantity <= threshold)
            .OrderBy(i => i.Quantity)
            .Select(i => new Inventory
            {
                ProductId = i.ProductId,
                Quantity = i.Quantity,
                WarehouseId = i.WarehouseId,
                Product = new Product { Name = i.Product.Name, SKU = i.Product.SKU }
            })
            .ToListAsync();
    }

    public async Task UpdateQuantityAsync(int productId, int quantityChange)
    {
        // Raw SQL for atomic update
        await _db.Database.ExecuteSqlRawAsync(
            "UPDATE Inventory SET Quantity = Quantity + {0} WHERE ProductId = {1} AND Quantity + {0} >= 0",
            quantityChange, productId);
    }

    public async Task<Dictionary<int, int>> GetBulkStockAsync(List<int> productIds)
    {
        return await _db.Inventory
            .Where(i => productIds.Contains(i.ProductId))
            .ToDictionaryAsync(i => i.ProductId, i => i.Quantity);
    }
}
