using Microsoft.EntityFrameworkCore;
using ECommerceApp.Models;

namespace ECommerceApp.Data;

public class AppDbContext : DbContext
{
    public AppDbContext(DbContextOptions<AppDbContext> options) : base(options) { }

    public DbSet<User> Users => Set<User>();
    public DbSet<Profile> Profiles => Set<Profile>();
    public DbSet<Address> Addresses => Set<Address>();
    public DbSet<Product> Products => Set<Product>();
    public DbSet<Category> Categories => Set<Category>();
    public DbSet<Order> Orders => Set<Order>();
    public DbSet<OrderItem> OrderItems => Set<OrderItem>();
    public DbSet<Review> Reviews => Set<Review>();
    public DbSet<Inventory> Inventory => Set<Inventory>();

    protected override void OnModelCreating(ModelBuilder modelBuilder)
    {
        // User
        modelBuilder.Entity<User>(e =>
        {
            e.HasKey(u => u.Id);
            e.HasIndex(u => u.Email).IsUnique();
            e.HasIndex(u => u.Username).IsUnique();
            e.HasOne(u => u.Profile).WithOne(p => p.User).HasForeignKey<Profile>(p => p.UserId);
            e.HasMany(u => u.Addresses).WithOne(a => a.User).HasForeignKey(a => a.UserId);
            e.HasMany(u => u.Orders).WithOne(o => o.User).HasForeignKey(o => o.UserId);
            e.HasMany(u => u.Reviews).WithOne(r => r.User).HasForeignKey(r => r.UserId);
        });

        // Product
        modelBuilder.Entity<Product>(e =>
        {
            e.HasKey(p => p.Id);
            e.HasIndex(p => p.SKU).IsUnique();
            e.HasOne(p => p.Category).WithMany(c => c.Products).HasForeignKey(p => p.CategoryId);
            e.HasOne(p => p.Inventory).WithOne(i => i.Product).HasForeignKey<Inventory>(i => i.ProductId);
            e.HasMany(p => p.Reviews).WithOne(r => r.Product).HasForeignKey(r => r.ProductId);
        });

        // Category self-referencing
        modelBuilder.Entity<Category>(e =>
        {
            e.HasKey(c => c.Id);
            e.HasOne(c => c.ParentCategory).WithMany(c => c.SubCategories).HasForeignKey(c => c.ParentCategoryId);
        });

        // Order
        modelBuilder.Entity<Order>(e =>
        {
            e.HasKey(o => o.Id);
            e.HasIndex(o => new { o.UserId, o.CreatedDate });
            e.HasIndex(o => new { o.Status, o.CreatedDate });
            e.HasMany(o => o.Items).WithOne(i => i.Order).HasForeignKey(i => i.OrderId).OnDelete(DeleteBehavior.Cascade);
        });

        // OrderItem
        modelBuilder.Entity<OrderItem>(e =>
        {
            e.HasKey(i => i.Id);
            e.HasOne(i => i.Product).WithMany(p => p.OrderItems).HasForeignKey(i => i.ProductId);
            e.Ignore(i => i.Subtotal);
        });

        // Review
        modelBuilder.Entity<Review>(e =>
        {
            e.HasKey(r => r.Id);
            e.HasIndex(r => new { r.ProductId, r.CreatedDate });
            e.HasIndex(r => new { r.UserId, r.ProductId }).IsUnique(); // one review per user per product
        });

        // Inventory
        modelBuilder.Entity<Inventory>(e =>
        {
            e.HasKey(i => i.Id);
            e.HasIndex(i => i.ProductId).IsUnique();
        });
    }
}
