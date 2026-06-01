using Microsoft.AspNetCore.Mvc;
using ECommerceApp.Repositories;
using ECommerceApp.Services;
using ECommerceApp.Models;

namespace ECommerceApp.Controllers;

[ApiController]
[Route("api/[controller]")]
public class ProductController : ControllerBase
{
    private readonly ProductRepository _productRepo;
    private readonly ReviewRepository _reviewRepo;
    private readonly InventoryRepository _inventoryRepo;

    public ProductController(ProductRepository productRepo, ReviewRepository reviewRepo, InventoryRepository inventoryRepo)
    {
        _productRepo = productRepo;
        _reviewRepo = reviewRepo;
        _inventoryRepo = inventoryRepo;
    }

    [HttpGet("{id}")]
    public async Task<IActionResult> GetProduct(int id)
    {
        var product = await _productRepo.GetByIdAsync(id);
        if (product == null) return NotFound();

        var inventory = await _inventoryRepo.GetByProductIdAsync(id);
        return Ok(new { product, inStock = inventory?.Quantity > 0 });
    }

    [HttpGet("category/{categoryId}")]
    public async Task<IActionResult> GetByCategory(int categoryId, [FromQuery] int page = 1,
        [FromQuery] string sortBy = "date", [FromQuery] decimal? minPrice = null, [FromQuery] decimal? maxPrice = null)
    {
        if (sortBy == "price")
        {
            var products = await _productRepo.GetByCategoryPriceSortedAsync(categoryId, minPrice, maxPrice);
            return Ok(products);
        }

        var result = await _productRepo.GetByCategoryAsync(categoryId, page);
        return Ok(result);
    }

    [HttpGet("search")]
    public async Task<IActionResult> Search([FromQuery] string q)
    {
        var products = await _productRepo.SearchAsync(q);
        return Ok(products);
    }

    [HttpGet("featured")]
    public async Task<IActionResult> GetFeatured()
    {
        var products = await _productRepo.GetTopRatedAsync(10);
        return Ok(products);
    }

    [HttpGet("{id}/related")]
    public async Task<IActionResult> GetRelated(int id)
    {
        var products = await _productRepo.GetRelatedProductsAsync(id);
        return Ok(products);
    }

    [HttpGet("{id}/reviews")]
    public async Task<IActionResult> GetReviews(int id, [FromQuery] int page = 1)
    {
        var reviews = await _reviewRepo.GetByProductIdAsync(id, page);
        return Ok(reviews);
    }
}
