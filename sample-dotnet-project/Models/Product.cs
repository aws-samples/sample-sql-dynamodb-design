namespace ECommerceApp.Models;

public class Product
{
    public int Id { get; set; }
    public string Name { get; set; } = string.Empty;
    public string Description { get; set; } = string.Empty;
    public decimal Price { get; set; }
    public string SKU { get; set; } = string.Empty;
    public string? ThumbnailUrl { get; set; }
    public double AverageRating { get; set; }
    public int ReviewCount { get; set; }
    public bool IsActive { get; set; } = true;
    public DateTime CreatedDate { get; set; } = DateTime.UtcNow;

    public int CategoryId { get; set; }
    public Category Category { get; set; } = null!;
    public Inventory? Inventory { get; set; }
    public ICollection<OrderItem> OrderItems { get; set; } = new List<OrderItem>();
    public ICollection<Review> Reviews { get; set; } = new List<Review>();
}

public class Category
{
    public int Id { get; set; }
    public string Name { get; set; } = string.Empty;
    public string? Slug { get; set; }
    public int? ParentCategoryId { get; set; }

    public Category? ParentCategory { get; set; }
    public ICollection<Category> SubCategories { get; set; } = new List<Category>();
    public ICollection<Product> Products { get; set; } = new List<Product>();
}

public class Inventory
{
    public int Id { get; set; }
    public int ProductId { get; set; }
    public int Quantity { get; set; }
    public string WarehouseId { get; set; } = string.Empty;
    public DateTime LastRestockedDate { get; set; }

    public Product Product { get; set; } = null!;
}
