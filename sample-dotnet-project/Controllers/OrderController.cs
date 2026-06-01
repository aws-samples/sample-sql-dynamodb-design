using Microsoft.AspNetCore.Mvc;
using ECommerceApp.Repositories;
using ECommerceApp.Services;
using ECommerceApp.Models;

namespace ECommerceApp.Controllers;

[ApiController]
[Route("api/[controller]")]
public class OrderController : ControllerBase
{
    private readonly OrderRepository _orderRepo;
    private readonly OrderService _orderService;

    public OrderController(OrderRepository orderRepo, OrderService orderService)
    {
        _orderRepo = orderRepo;
        _orderService = orderService;
    }

    [HttpGet("{id}")]
    public async Task<IActionResult> GetOrder(Guid id)
    {
        var order = await _orderRepo.GetByIdAsync(id);
        if (order == null) return NotFound();
        return Ok(order);
    }

    [HttpGet("my")]
    public async Task<IActionResult> GetMyOrders([FromQuery] Guid userId, [FromQuery] int page = 1,
        [FromQuery] OrderStatus? status = null)
    {
        if (status.HasValue)
        {
            var filtered = await _orderRepo.GetByUserAndStatusAsync(userId, status.Value);
            return Ok(filtered);
        }

        var orders = await _orderRepo.GetByUserIdAsync(userId, page);
        return Ok(orders);
    }

    [HttpPost]
    public async Task<IActionResult> PlaceOrder([FromBody] PlaceOrderRequest request)
    {
        var order = await _orderService.PlaceOrderAsync(
            request.UserId,
            request.Items.Select(i => (i.ProductId, i.Quantity)).ToList());
        return CreatedAtAction(nameof(GetOrder), new { id = order.Id }, order);
    }

    [HttpPut("{id}/status")]
    public async Task<IActionResult> UpdateStatus(Guid id, [FromBody] UpdateStatusRequest request)
    {
        await _orderService.UpdateStatusAsync(id, request.Status);
        return NoContent();
    }
}

[ApiController]
[Route("api/admin/orders")]
public class AdminOrderController : ControllerBase
{
    private readonly OrderRepository _orderRepo;

    public AdminOrderController(OrderRepository orderRepo) => _orderRepo = orderRepo;

    [HttpGet]
    public async Task<IActionResult> GetOrders([FromQuery] OrderStatus status,
        [FromQuery] DateTime? from, [FromQuery] DateTime? to)
    {
        var orders = await _orderRepo.GetByStatusAsync(status, from, to);
        return Ok(orders);
    }

    [HttpGet("report")]
    public async Task<IActionResult> GetDateRange([FromQuery] DateTime from, [FromQuery] DateTime to)
    {
        var orders = await _orderRepo.GetByDateRangeAsync(from, to);
        return Ok(orders);
    }
}

public record PlaceOrderRequest(Guid UserId, List<OrderItemRequest> Items);
public record OrderItemRequest(int ProductId, int Quantity);
public record UpdateStatusRequest(OrderStatus Status);
