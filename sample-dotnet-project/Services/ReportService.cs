using ECommerceApp.Data;
using ECommerceApp.Models;
using Microsoft.EntityFrameworkCore;

namespace ECommerceApp.Services;

public class ReportService
{
    private readonly AppDbContext _db;
    public ReportService(AppDbContext db) => _db = db;

    public async Task<SalesReport> GetSalesReportAsync(DateTime from, DateTime to)
    {
        var orders = await _db.Orders
            .Where(o => o.CreatedDate >= from && o.CreatedDate <= to && o.Status != OrderStatus.Cancelled)
            .ToListAsync();

        return new SalesReport
        {
            TotalOrders = orders.Count,
            TotalRevenue = orders.Sum(o => o.Total),
            AverageOrderValue = orders.Any() ? orders.Average(o => o.Total) : 0,
            OrdersByStatus = orders.GroupBy(o => o.Status)
                .ToDictionary(g => g.Key.ToString(), g => g.Count())
        };
    }

    // Raw SQL for complex aggregation
    public async Task<List<CategorySalesDto>> GetTopCategoriesByRevenueAsync(DateTime from, DateTime to, int top = 10)
    {
        return await _db.Database
            .SqlQueryRaw<CategorySalesDto>(@"
                SELECT c.Name AS CategoryName, 
                       COUNT(DISTINCT o.Id) AS OrderCount,
                       SUM(oi.Quantity * oi.UnitPrice) AS TotalRevenue
                FROM Categories c
                INNER JOIN Products p ON p.CategoryId = c.Id
                INNER JOIN OrderItems oi ON oi.ProductId = p.Id
                INNER JOIN Orders o ON o.Id = oi.OrderId
                WHERE o.CreatedDate BETWEEN {0} AND {1}
                  AND o.Status NOT IN ('Cancelled', 'Refunded')
                GROUP BY c.Id, c.Name
                ORDER BY TotalRevenue DESC
                OFFSET 0 ROWS FETCH NEXT {2} ROWS ONLY",
                from, to, top)
            .ToListAsync();
    }

    public async Task<List<DailyRevenueDto>> GetDailyRevenueAsync(DateTime from, DateTime to)
    {
        return await _db.Orders
            .Where(o => o.CreatedDate >= from && o.CreatedDate <= to && o.Status != OrderStatus.Cancelled)
            .GroupBy(o => o.CreatedDate.Date)
            .Select(g => new DailyRevenueDto
            {
                Date = g.Key,
                OrderCount = g.Count(),
                Revenue = g.Sum(o => o.Total)
            })
            .OrderBy(d => d.Date)
            .ToListAsync();
    }
}

public class SalesReport
{
    public int TotalOrders { get; set; }
    public decimal TotalRevenue { get; set; }
    public decimal AverageOrderValue { get; set; }
    public Dictionary<string, int> OrdersByStatus { get; set; } = new();
}

public class CategorySalesDto
{
    public string CategoryName { get; set; } = string.Empty;
    public int OrderCount { get; set; }
    public decimal TotalRevenue { get; set; }
}

public class DailyRevenueDto
{
    public DateTime Date { get; set; }
    public int OrderCount { get; set; }
    public decimal Revenue { get; set; }
}
