using CommunityToolkit.Mvvm.ComponentModel;
using Demo.Core.Models;
using System.Windows.Input;

namespace Demo.App.ViewModels
{
    [ObservableProperty]
    public partial class MainViewModel : ObservableObject
    {
        private readonly IHost _host;

        public string StatusText { get; set; } = "就绪";

        public void Navigate()
        {
        }
    }
}
