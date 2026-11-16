using System.Linq;

namespace Demo.Core.Models;

public enum Kind { Fire, Water }

public record Pokemon(string Name, int Level);

public class Repository
{
    public ObservableCollection<Pokemon> Items { get; } = new();

    public async Task<Pokemon?> FindAsync(string name)
    {
        return null;
    }
}
