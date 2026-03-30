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


def create_offset_figure(
    fig_width_cm: float,
    fig_height_cm: float,
    ax_width_cm: float,
    ax_height_cm: float,
    left_margin_scale: float = 0.8,
    bottom_margin_scale: float = 0.8,
    dpi: int = 300,
):
    if ax_width_cm > fig_width_cm or ax_height_cm > fig_height_cm:
        raise ValueError("Axis dimensions must be smaller than figure dimensions.")

    left_cm = (fig_width_cm - ax_width_cm) * left_margin_scale
    bottom_cm = (fig_height_cm - ax_height_cm) * bottom_margin_scale

    fig = plt.figure(
        figsize=(cm_to_inch(fig_width_cm), cm_to_inch(fig_height_cm)),
        dpi=dpi,
    )
    ax = fig.add_axes(
        [
            left_cm / fig_width_cm,
            bottom_cm / fig_height_cm,
            ax_width_cm / fig_width_cm,
            ax_height_cm / fig_height_cm,
        ]
    )
    return fig, ax



if __name__ == "__main__":

    fig,ax=create_offset_figure(5.0, 4.0, 4, 3.2,0.8,0.8)
    plt.show()
    plt.savefig("test.svg", format="svg", bbox_inches="tight", pad_inches=0.01)
