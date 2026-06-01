using Microsoft.EntityFrameworkCore;
using ECommerceApp.Data;
using ECommerceApp.Models;
using ECommerceApp.Repositories;

namespace ECommerceApp.Services;

public class OrderService
{
    private readonly AppDbContext _db;
    private readonly OrderRepository _orderRepo;
    private readonly InventoryRepository _inventoryRepo;

    public OrderService(AppDbContext db, OrderRepository orderRepo, InventoryRepository inventoryRepo)
    {
        _db = db;
        _orderRepo = orderRepo;
        _inventoryRepo = inventoryRepo;
    }

    public async Task<Order> PlaceOrderAsync(Guid userId, List<(int ProductId, int Quantity)> items)
    {
        using var transaction = await _db.Database.BeginTransactionAsync();

        try
        {
            var productIds = items.Select(i => i.ProductId).ToList();
            var products = await _db.Products
                .Where(p => productIds.Contains(p.Id))
                .ToDictionaryAsync(p => p.Id);

            var stock = await _inventoryRepo.GetBulkStockAsync(productIds);

            // Validate stock
            foreach (var (productId, qty) in items)
            {
                if (!stock.ContainsKey(productId) || stock[productId] < qty)
                    throw new InvalidOperationException($"Insufficient stock for product {productId}");
            }

            var order = new Order
            {
                Id = Guid.NewGuid(),
                UserId = userId,
                Status = OrderStatus.Pending,
                CreatedDate = DateTime.UtcNow,
                Items = items.Select(i => new OrderItem
                {
                    Id = Guid.NewGuid(),
                    ProductId = i.ProductId,
                    ProductName = products[i.ProductId].Name,
                    Quantity = i.Quantity,
                    UnitPrice = products[i.ProductId].Price
                }).ToList()
            };

            order.Total = order.Items.Sum(i => i.Quantity * i.UnitPrice);
            order.Tax = order.Total * 0.08m;
            order.ShippingCost = order.Total > 50 ? 0 : 5.99m;

            _db.Orders.Add(order);

            // Decrement inventory
            foreach (var (productId, qty) in items)
            {
                await _inventoryRepo.UpdateQuantityAsync(productId, -qty);
            }

            await _db.SaveChangesAsync();
            await transaction.CommitAsync();

            return order;
        }
        catch
        {
            await transaction.RollbackAsync();
            throw;
        }
    }

    public async Task UpdateStatusAsync(Guid orderId, OrderStatus newStatus)
    {
        var order = await _db.Orders.FindAsync(orderId);
        if (order == null) throw new KeyNotFoundException("Order not found");

        // Validate transition
        var validTransitions = new Dictionary<OrderStatus, OrderStatus[]>
        {
            [OrderStatus.Pending] = new[] { OrderStatus.Confirmed, OrderStatus.Cancelled },
            [OrderStatus.Confirmed] = new[] { OrderStatus.Processing, OrderStatus.Cancelled },
            [OrderStatus.Processing] = new[] { OrderStatus.Shipped },
            [OrderStatus.Shipped] = new[] { OrderStatus.Delivered },
            [OrderStatus.Delivered] = new[] { OrderStatus.Refunded },
        };

        if (!validTransitions.ContainsKey(order.Status) ||
            !validTransitions[order.Status].Contains(newStatus))
            throw new InvalidOperationException($"Cannot transition from {order.Status} to {newStatus}");

        await _orderRepo.UpdateStatusAsync(orderId, newStatus);
    }
}
