import matplotlib.pyplot as plt

CM_PER_INCH = 2.54

plt.rcParams.update(
    {
        "font.family": ["Arial", "SimSun"],
        "axes.labelsize": 6,
        "axes.titlesize": 6,
        "axes.linewidth": 1.0,
        "axes.labelpad": 0,
        "xtick.major.width": 1.1,
        "ytick.major.width": 1.1,
        "xtick.direction": "in",
        "ytick.direction": "in",
        "xtick.labelsize": 6,
        "ytick.labelsize": 6,
        "lines.linewidth": 1.2,
        "legend.fontsize": 5,
        "legend.frameon": False,
        "svg.fonttype": "none",
    }
)


def cm_to_inch(value_cm: float) -> float:
    return value_cm / CM_PER_INCH


def create_offset_figure_with_padding(
    ax_width_cm: float,
    ax_height_cm: float,
    padding: float = 0.2,
    dpi: int = 600,
):
    if ax_width_cm <= 0 or ax_height_cm <= 0:
        raise ValueError("Axis dimensions must be positive.")

    if padding < 0:
        raise ValueError("padding must be non-negative.")

    left_margin_cm = right_margin_cm = ax_width_cm * padding
    bottom_margin_cm = top_margin_cm = ax_height_cm * padding
    fig_width_cm = left_margin_cm + ax_width_cm + right_margin_cm
    fig_height_cm = bottom_margin_cm + ax_height_cm + top_margin_cm

    fig = plt.figure(
        figsize=(cm_to_inch(fig_width_cm), cm_to_inch(fig_height_cm)),
        dpi=dpi,
    )
    ax = fig.add_axes(
        [
            left_margin_cm / fig_width_cm,
            bottom_margin_cm / fig_height_cm,
            ax_width_cm / fig_width_cm,
            ax_height_cm / fig_height_cm,
        ]
    )
    return fig, ax




if __name__ == "__main__":


    fig,ax=create_offset_figure_with_padding(2, 1, padding=0.8)
    x=[1, 2, 3, 4, 5]
    y=[1, 4, 9, 16, 25]
    ax.plot(x, y)
    ax.set_xlabel('X-axis')
    ax.set_ylabel('Y-axis')
    ax.set_title('Sample Plot')
 
    plt.savefig('sample_plot.svg', format='svg', bbox_inches='tight', pad_inches=0.01)
