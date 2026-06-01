namespace ECommerceApp.Models;

public class Review
{
    public Guid Id { get; set; }
    public int ProductId { get; set; }
    public Guid UserId { get; set; }
    public string UserName { get; set; } = string.Empty;
    public int Rating { get; set; }
    public string? Title { get; set; }
    public string? Comment { get; set; }
    public bool IsVerifiedPurchase { get; set; }
    public DateTime CreatedDate { get; set; } = DateTime.UtcNow;

    public Product Product { get; set; } = null!;
    public User User { get; set; } = null!;
}
