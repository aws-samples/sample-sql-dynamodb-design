using Microsoft.EntityFrameworkCore;
using ECommerceApp.Data;
using ECommerceApp.Models;

namespace ECommerceApp.Repositories;

public class OrderRepository
{
    private readonly AppDbContext _db;
    public OrderRepository(AppDbContext db) => _db = db;

    public async Task<Order?> GetByIdAsync(Guid orderId)
    {
        return await _db.Orders
            .Include(o => o.Items)
                .ThenInclude(i => i.Product)
            .Include(o => o.User)
            .FirstOrDefaultAsync(o => o.Id == orderId);
    }

    public async Task<List<Order>> GetByUserIdAsync(Guid userId, int page = 1, int pageSize = 10)
    {
        return await _db.Orders
            .Include(o => o.Items)
            .Where(o => o.UserId == userId)
            .OrderByDescending(o => o.CreatedDate)
            .Skip((page - 1) * pageSize)
            .Take(pageSize)
            .ToListAsync();
    }

    public async Task<List<Order>> GetByUserAndStatusAsync(Guid userId, OrderStatus status)
    {
        return await _db.Orders
            .Where(o => o.UserId == userId && o.Status == status)
            .OrderByDescending(o => o.CreatedDate)
            .Select(o => new Order
            {
                Id = o.Id,
                Status = o.Status,
                Total = o.Total,
                CreatedDate = o.CreatedDate
            })
            .ToListAsync();
    }

    public async Task<List<Order>> GetByStatusAsync(OrderStatus status, DateTime? from, DateTime? to)
    {
        var query = _db.Orders
            .Include(o => o.User)
            .Where(o => o.Status == status);

        if (from.HasValue)
            query = query.Where(o => o.CreatedDate >= from.Value);
        if (to.HasValue)
            query = query.Where(o => o.CreatedDate <= to.Value);

        return await query
            .OrderByDescending(o => o.CreatedDate)
            .Select(o => new Order
            {
                Id = o.Id,
                Status = o.Status,
                Total = o.Total,
                CreatedDate = o.CreatedDate,
                User = new User { FirstName = o.User.FirstName, LastName = o.User.LastName }
            })
            .ToListAsync();
    }

    public async Task<List<Order>> GetByDateRangeAsync(DateTime from, DateTime to)
    {
        return await _db.Orders
            .Where(o => o.CreatedDate >= from && o.CreatedDate <= to)
            .OrderBy(o => o.CreatedDate)
            .Select(o => new Order
            {
                Id = o.Id,
                Total = o.Total,
                Status = o.Status,
                CreatedDate = o.CreatedDate
            })
            .ToListAsync();
    }

    public async Task<Order> CreateAsync(Order order)
    {
        _db.Orders.Add(order);
        await _db.SaveChangesAsync();
        return order;
    }

    public async Task UpdateStatusAsync(Guid orderId, OrderStatus newStatus)
    {
        var order = await _db.Orders.FindAsync(orderId);
        if (order != null)
        {
            order.Status = newStatus;
            order.UpdatedDate = DateTime.UtcNow;
            await _db.SaveChangesAsync();
        }
    }
}
