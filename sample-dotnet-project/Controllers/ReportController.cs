using Microsoft.AspNetCore.Mvc;
using ECommerceApp.Services;

namespace ECommerceApp.Controllers;

[ApiController]
[Route("api/admin/reports")]
public class ReportController : ControllerBase
{
    private readonly ReportService _reportService;
    public ReportController(ReportService reportService) => _reportService = reportService;

    [HttpGet("sales")]
    public async Task<IActionResult> GetSalesReport([FromQuery] DateTime from, [FromQuery] DateTime to)
    {
        var report = await _reportService.GetSalesReportAsync(from, to);
        return Ok(report);
    }

    [HttpGet("top-categories")]
    public async Task<IActionResult> GetTopCategories([FromQuery] DateTime from, [FromQuery] DateTime to, [FromQuery] int top = 10)
    {
        var categories = await _reportService.GetTopCategoriesByRevenueAsync(from, to, top);
        return Ok(categories);
    }

    [HttpGet("daily-revenue")]
    public async Task<IActionResult> GetDailyRevenue([FromQuery] DateTime from, [FromQuery] DateTime to)
    {
        var data = await _reportService.GetDailyRevenueAsync(from, to);
        return Ok(data);
    }
}
