using Microsoft.AspNetCore.Mvc;
using ECommerceApp.Repositories;
using ECommerceApp.Services;

namespace ECommerceApp.Controllers;

[ApiController]
[Route("api/[controller]")]
public class UserController : ControllerBase
{
    private readonly UserRepository _userRepo;
    private readonly ReviewRepository _reviewRepo;

    public UserController(UserRepository userRepo, ReviewRepository reviewRepo)
    {
        _userRepo = userRepo;
        _reviewRepo = reviewRepo;
    }

    [HttpGet("{id}")]
    public async Task<IActionResult> GetUser(Guid id)
    {
        var user = await _userRepo.GetByIdAsync(id);
        if (user == null) return NotFound();
        return Ok(user);
    }

    [HttpGet("profile/{username}")]
    public async Task<IActionResult> GetByUsername(string username)
    {
        var user = await _userRepo.GetByUsernameAsync(username);
        if (user == null) return NotFound();
        return Ok(user);
    }

    [HttpGet("{id}/reviews")]
    public async Task<IActionResult> GetUserReviews(Guid id)
    {
        var reviews = await _reviewRepo.GetByUserIdAsync(id);
        return Ok(reviews);
    }

    [HttpPost("{id}/reviews")]
    public async Task<IActionResult> SubmitReview(Guid id, [FromBody] SubmitReviewRequest request,
        [FromServices] ReviewService reviewService)
    {
        var review = await reviewService.SubmitReviewAsync(id, request.ProductId, request.Rating, request.Title, request.Comment);
        return Created($"/api/user/{id}/reviews", review);
    }
}

[ApiController]
[Route("api/admin/users")]
public class AdminUserController : ControllerBase
{
    private readonly UserRepository _userRepo;
    public AdminUserController(UserRepository userRepo) => _userRepo = userRepo;

    [HttpGet("search")]
    public async Task<IActionResult> Search([FromQuery] string q, [FromQuery] int page = 1)
    {
        var users = await _userRepo.SearchUsersAsync(q, page);
        return Ok(users);
    }

    [HttpGet("recent")]
    public async Task<IActionResult> GetRecent([FromQuery] int days = 30)
    {
        var users = await _userRepo.GetRecentUsersAsync(days);
        return Ok(users);
    }

    [HttpGet("count")]
    public async Task<IActionResult> GetCount()
    {
        var count = await _userRepo.GetTotalCountAsync();
        return Ok(new { count });
    }
}

public record SubmitReviewRequest(int ProductId, int Rating, string? Title, string? Comment);
